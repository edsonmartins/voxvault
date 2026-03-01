use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    response::IntoResponse,
    routing::get,
    Router,
};
use serde::Serialize;
use std::sync::Arc;
use tokio::sync::broadcast;
use tracing::{error, info, warn};

/// Message sent to WebSocket clients.
#[derive(Debug, Clone, Serialize)]
pub struct TranscriptMessage {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub text: String,
    pub language: String,
    pub timestamp: u64,
    pub is_final: bool,
    /// Real-Time Factor (processing_time / audio_duration). Only set for final transcripts.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rtf: Option<f64>,
}

impl TranscriptMessage {
    /// Create a transcript message.
    pub fn transcript(
        text: String,
        language: String,
        timestamp: u64,
        is_final: bool,
        rtf: Option<f64>,
    ) -> Self {
        Self {
            msg_type: "transcript".to_string(),
            text,
            language,
            timestamp,
            is_final,
            rtf,
        }
    }

    /// Create a status message.
    pub fn status(text: String) -> Self {
        Self {
            msg_type: "status".to_string(),
            text,
            language: String::new(),
            timestamp: chrono::Utc::now().timestamp_millis() as u64,
            is_final: false,
            rtf: None,
        }
    }

    /// Create an error message.
    pub fn error(text: String) -> Self {
        Self {
            msg_type: "error".to_string(),
            text,
            language: String::new(),
            timestamp: chrono::Utc::now().timestamp_millis() as u64,
            is_final: false,
            rtf: None,
        }
    }
}

/// Shared state for the WebSocket server.
#[derive(Clone)]
pub struct ServerState {
    pub tx: broadcast::Sender<TranscriptMessage>,
}

/// WebSocket server that broadcasts transcript messages to connected clients.
pub struct TranscriptServer {
    port: u16,
    state: Arc<ServerState>,
}

impl TranscriptServer {
    /// Create a new server on the specified port.
    pub fn new(port: u16) -> Self {
        let (tx, _) = broadcast::channel(256);
        Self {
            port,
            state: Arc::new(ServerState { tx }),
        }
    }

    /// Get a sender to publish transcript messages.
    pub fn sender(&self) -> broadcast::Sender<TranscriptMessage> {
        self.state.tx.clone()
    }

    /// Run the server (blocks until shutdown).
    pub async fn run(&self) -> anyhow::Result<()> {
        let app = Router::new()
            .route("/", get(ws_handler))
            .route("/health", get(health_handler))
            .with_state(self.state.clone());

        let addr = format!("127.0.0.1:{}", self.port);
        let listener = tokio::net::TcpListener::bind(&addr).await?;
        info!(addr, "WebSocket server listening");

        axum::serve(listener, app).await?;
        Ok(())
    }
}

/// Health check endpoint.
async fn health_handler() -> &'static str {
    "ok"
}

/// WebSocket upgrade handler.
async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<ServerState>>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, state))
}

/// Handle a single WebSocket connection.
async fn handle_socket(mut socket: WebSocket, state: Arc<ServerState>) {
    info!("WebSocket client connected");
    let mut rx = state.tx.subscribe();

    loop {
        tokio::select! {
            // Forward broadcast messages to this client
            result = rx.recv() => {
                match result {
                    Ok(msg) => {
                        let json = match serde_json::to_string(&msg) {
                            Ok(j) => j,
                            Err(e) => {
                                error!("Failed to serialize message: {}", e);
                                continue;
                            }
                        };
                        if socket.send(Message::Text(json.into())).await.is_err() {
                            info!("WebSocket client disconnected (send failed)");
                            break;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        warn!(skipped = n, "Client lagging behind, skipped messages");
                    }
                    Err(broadcast::error::RecvError::Closed) => {
                        info!("Broadcast channel closed");
                        break;
                    }
                }
            }
            // Handle incoming messages from client (ping/pong, close)
            result = socket.recv() => {
                match result {
                    Some(Ok(Message::Close(_))) | None => {
                        info!("WebSocket client disconnected");
                        break;
                    }
                    Some(Ok(Message::Ping(data))) => {
                        if socket.send(Message::Pong(data)).await.is_err() {
                            break;
                        }
                    }
                    Some(Ok(_)) => {
                        // Ignore other messages from client
                    }
                    Some(Err(e)) => {
                        warn!("WebSocket error: {}", e);
                        break;
                    }
                }
            }
        }
    }
}
