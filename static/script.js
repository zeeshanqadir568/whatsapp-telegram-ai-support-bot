// State management
let currentSessionId = "session_" + Math.floor(Math.random() * 100000);

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
    fetchHealthStatus();
    fetchLeads();
    setInterval(fetchHealthStatus, 15000);
});

// Fetch system health diagnostics from /health
async function fetchHealthStatus() {
    try {
        const response = await fetch("/health");
        if (!response.ok) throw new Error("Health check failed");
        const data = await response.json();

        document.getElementById("val-llm").innerText = data.active_llm_provider || "N/A";
        document.getElementById("val-docs").innerText = data.vector_store_documents || 0;
        
        const badgeStatus = document.getElementById("badge-status");
        const valStatus = document.getElementById("val-status");

        if (data.status === "ok") {
            badgeStatus.className = "badge-card status-healthy";
            valStatus.innerText = "API Online";
        } else {
            badgeStatus.className = "badge-card";
            valStatus.innerText = "Offline";
        }
    } catch (error) {
        console.error("Error fetching health status:", error);
        document.getElementById("val-status").innerText = "Connection Error";
    }
}

// Fetch sales leads from /api/leads
async function fetchLeads() {
    try {
        const response = await fetch("/api/leads");
        if (!response.ok) return;
        const leads = await response.json();

        const tbody = document.getElementById("leads-table-body");
        const badgeCount = document.getElementById("leads-count-badge");

        badgeCount.innerText = leads.length;

        if (leads.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="empty-table">
                        <i class="fa-solid fa-inbox"></i> No leads captured yet. Send your email or phone number in chat to capture one!
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = leads.map(l => `
            <tr>
                <td><span class="badge-tag">${escapeHtml(l.channel || 'web')}</span></td>
                <td><strong>${escapeHtml(l.email || 'N/A')}</strong></td>
                <td>${escapeHtml(l.phone || 'N/A')}</td>
                <td>${escapeHtml(l.intent || 'support')}</td>
                <td><small>${escapeHtml(l.created_at || '')}</small></td>
            </tr>
        `).join('');
    } catch (error) {
        console.error("Error fetching leads:", error);
    }
}

// Quick Prompt click handler
function sendQuickPrompt(promptText) {
    const input = document.getElementById("chat-input");
    input.value = promptText;
    document.getElementById("chat-form").dispatchEvent(new Event("submit"));
}

// Handle chat message form submission
async function handleSendMessage(event) {
    event.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;

    const channel = document.getElementById("channel-select").value;

    // Append User Message to UI
    appendUserMessage(message);
    input.value = "";

    // Show Typing Indicator
    const typingId = appendTypingIndicator();

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                session_id: currentSessionId,
                channel: channel
            })
        });

        removeMessageElement(typingId);

        if (!response.ok) {
            const errData = await response.json();
            appendAssistantMessage("Error: " + (errData.detail || "Failed to process message"));
            return;
        }

        const data = await response.json();
        appendAssistantMessage(data.reply, data.sources, data.lead_captured);

        // If lead was captured, refresh leads table
        if (data.lead_captured) {
            fetchLeads();
        }

    } catch (error) {
        removeMessageElement(typingId);
        appendAssistantMessage("Network error: Could not reach the AI support API server.");
        console.error("Chat error:", error);
    }
}

// Append User Message to Chat Window
function appendUserMessage(text) {
    const container = document.getElementById("chat-messages");
    const msgDiv = document.createElement("div");
    msgDiv.className = "message user-msg";
    msgDiv.innerHTML = `<div class="msg-bubble">${escapeHtml(text)}</div>`;
    container.appendChild(msgDiv);
    scrollToBottom();
}

// Append Assistant Message to Chat Window
function appendAssistantMessage(replyText, sources = [], leadCaptured = false) {
    const container = document.getElementById("chat-messages");
    const msgDiv = document.createElement("div");
    msgDiv.className = "message assistant-msg";

    let sourcesHtml = "";
    if (sources && sources.length > 0) {
        sourcesHtml = `<div class="sources-badge"><i class="fa-solid fa-file-invoice"></i> Source: ${sources.map(s => escapeHtml(s)).join(", ")}</div>`;
    }

    let leadBadgeHtml = "";
    if (leadCaptured) {
        leadBadgeHtml = `<div class="lead-captured-badge"><i class="fa-solid fa-circle-check"></i> Contact Lead Captured & Saved to DB!</div>`;
    }

    msgDiv.innerHTML = `
        <div class="msg-bubble">${escapeHtml(replyText)}</div>
        ${sourcesHtml}
        ${leadBadgeHtml}
    `;
    container.appendChild(msgDiv);
    scrollToBottom();
}

// Typing Indicator
function appendTypingIndicator() {
    const container = document.getElementById("chat-messages");
    const id = "typing_" + Date.now();
    const msgDiv = document.createElement("div");
    msgDiv.id = id;
    msgDiv.className = "message assistant-msg";
    msgDiv.innerHTML = `<div class="msg-bubble" style="color: var(--text-muted);"><i class="fa-solid fa-ellipsis fa-beat"></i> AI is thinking...</div>`;
    container.appendChild(msgDiv);
    scrollToBottom();
    return id;
}

function removeMessageElement(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function scrollToBottom() {
    const container = document.getElementById("chat-messages");
    container.scrollTop = container.scrollHeight;
}

// Dashboard Tabs Switcher
function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(content => content.classList.remove("active"));

    event.currentTarget.classList.add("active");
    document.getElementById(tabId).classList.add("active");
}

// Copy cURL snippet
function copyCurl() {
    const snippet = document.getElementById("curl-snippet").innerText;
    navigator.clipboard.writeText(snippet);
    alert("cURL command copied to clipboard!");
}

// HTML Safety Helper
function escapeHtml(text) {
    if (!text) return "";
    return text.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
