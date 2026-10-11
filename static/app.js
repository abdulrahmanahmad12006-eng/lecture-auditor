// Lecture Auditor Frontend Logic

document.addEventListener('DOMContentLoaded', () => {
    // Status indicators
    const apiStatusDot = document.getElementById('api-status');
    const apiStatusText = document.getElementById('api-status-text');
    const dbStatusDot = document.getElementById('db-status');
    const dbStatusText = document.getElementById('db-status-text');

    // Simulate status checking (in a real app, you'd make API calls)
    function checkStatus() {
        // API status
        apiStatusDot.classList.remove('checking', 'online', 'offline');
        apiStatusDot.classList.add('checking');
        apiStatusText.textContent = 'API: Checking...';

        // DB status
        dbStatusDot.classList.remove('checking', 'online', 'offline');
        dbStatusDot.classList.add('checking');
        dbStatusText.textContent = 'DB: Checking...';

        // Simulate API response after 1 second
        setTimeout(() => {
            const isApiOnline = Math.random() > 0.2; // 80% chance of being online
            apiStatusDot.classList.remove('checking');
            if (isApiOnline) {
                apiStatusDot.classList.add('online');
                apiStatusText.textContent = 'API: Online';
            } else {
                apiStatusDot.classList.add('offline');
                apiStatusText.textContent = 'API: Offline';
            }
        }, 1000);

        // Simulate DB response after 1.5 seconds
        setTimeout(() => {
            const isDbOnline = Math.random() > 0.1; // 90% chance of being online
            dbStatusDot.classList.remove('checking');
            if (isDbOnline) {
                dbStatusDot.classList.add('online');
                dbStatusText.textContent = 'DB: Online';
            } else {
                dbStatusDot.classList.add('offline');
                dbStatusText.textContent = 'DB: Offline';
            }
        }, 1500);
    }

    // Initial status check
    checkStatus();
    // Periodically check status (every 10 seconds)
    setInterval(checkStatus, 10000);

    // Tab switching
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            // Remove active class from all buttons and contents
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.style.display = 'none');

            // Add active class to clicked button
            button.classList.add('active');
            // Show corresponding tab content
            const tabId = button.getAttribute('data-tab');
            document.getElementById(`${tabId}-tab`).style.display = 'block';
        });
    });

    // File upload handling
    const uploadBtn = document.getElementById('upload-btn');
    const pdfUpload = document.getElementById('pdf-upload');
    const uploadProgress = document.getElementById('upload-progress');

    uploadBtn.addEventListener('click', () => {
        const files = pdfUpload.files;
        if (files.length === 0) {
            alert('Please select PDF files to upload');
            return;
        }

        // Simulate upload progress
        uploadProgress.innerHTML = '<div></div>';
        const progressBar = uploadProgress.querySelector('div');
        let width = 0;
        const interval = setInterval(() => {
            if (width >= 100) {
                clearInterval(interval);
                uploadProgress.innerHTML = '<p>Upload complete!</p>';
            } else {
                width++;
                progressBar.style.width = width + '%';
            }
        }, 20);

        // Reset file input
        pdfUpload.value = '';
    });

    // Chat functionality
    const chatInput = document.getElementById('chat-input');
    const chatSend = document.getElementById('chat-send');
    const chatMessages = document.getElementById('chat-messages');

    function addMessage(content, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message');
        messageDiv.classList.add(isUser ? 'user' : 'bot');
        messageDiv.textContent = content;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function sendMessage() {
        const message = chatInput.value.trim();
        if (message === '') return;

        // Add user message
        addMessage(message, true);
        chatInput.value = '';

        // Simulate bot response (in a real app, you'd send to backend)
        setTimeout(() => {
            const responses = [
                "That's an interesting question about the lecture material.",
                "Based on the indexed documents, here's what I found:",
                "I need to check the lecture notes for that specific topic.",
                "Let me search through the indexed content for relevant information.",
                "According to the lecture slides, the answer is:"
            ];
            const randomResponse = responses[Math.floor(Math.random() * responses.length)];
            addMessage(randomResponse, false);

            // Add a fake citation
            setTimeout(() => {
                const citationDiv = document.createElement('div');
                citationDiv.classList.add('citation');
                citationDiv.textContent = 'Source: Lecture 3, Page 12';
                const lastBotMessage = chatMessages.lastElementChild;
                lastBotMessage.appendChild(citationDiv);
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }, 500);
        }, 1000);
    }

    chatSend.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // Evals dashboard placeholder
    // In a real app, you would fetch evaluation metrics from the backend
    function loadEvalsMetrics() {
        const evalsContent = document.getElementById('evals-content');
        evalsContent.innerHTML = `
            <div class="metrics-grid">
                <div class="metric-card">
                    <h3><span>📊</span> Overall Accuracy</h3>
                    <div class="metric-value">87.5%</div>
                    <div class="metric-label">Average across all lectures</div>
                </div>
                <div class="metric-card">
                    <h3><span>⏱️</span> Avg Response Time</h3>
                    <div class="metric-value">1.2s</div>
                    <div class="metric-label">Time to answer queries</div>
                </div>
                <div class="metric-card">
                    <h3><span>📚</span> Documents Indexed</h3>
                    <div class="metric-value">24</div>
                    <div class="metric-label">PDF lectures processed</div>
                </div>
                <div class="metric-card">
                    <h3><span>🎯</span> Precision@3</h3>
                    <div class="metric-value">0.92</div>
                    <div class="metric-label">Relevance of top 3 results</div>
                </div>
            </div>
        `;
    }

    // Load evals metrics when tab is activated
    const evalsTabBtn = document.querySelector('.tab-btn[data-tab="evals"]');
    evalsTabBtn.addEventListener('click', loadEvalsMetrics);

    // Initial load of evals metrics (optional)
    // loadEvalsMetrics();
});