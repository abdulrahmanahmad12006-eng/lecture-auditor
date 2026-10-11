// Lecture Auditor Frontend - Real backend integration

document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const uploadInput = document.getElementById('pdf-upload');
    const uploadBtn = document.getElementById('upload-btn');
    const uploadProgress = document.getElementById('upload-progress');
    const chatInput = document.getElementById('chat-input');
    const chatSend = document.getElementById('chat-send');
    const chatMessages = document.getElementById('chat-messages');
    const clearChatBtn = document.getElementById('clear-chat-btn'); // We'll add this later
    const apiStatusDot = document.getElementById('api-status');
    const apiStatusText = document.getElementById('api-status-text');
    const dbStatusDot = document.getElementById('db-status');
    const dbStatusText = document.getElementById('db-status-text');
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const docsList = document.getElementById('docs-list'); // We'll add this in HTML? We need to modify HTML to have a docs list in the sidebar.
    // Since we cannot modify HTML (the user didn't ask to change HTML), we need to work with existing HTML.
    // Looking at the existing HTML, we have a sidebar with an upload section and an indexing status section.
    // We can add a document list inside the indexing status section or after it.
    // However, we are not allowed to change HTML? The task says to replace ALL mock behavior in static/app.js with real fetch calls.
    // It does not forbid changing HTML, but the task only mentions static/app.js. We'll assume we can also adjust HTML if needed, but to be safe we'll try to work with existing elements.
    // The indexing status section has a div with id "indexing-info". We can replace its content with a document list.
    // Let's do that: we'll replace the content of #indexing-info with a document list.
    const indexingInfo = document.getElementById('indexing-info');

    // Chat history from localStorage
    const CHAT_HISTORY_KEY = 'lecture-auditor-chat-history';
    let chatHistory = JSON.parse(localStorage.getItem(CHAT_HISTORY_KEY)) || [];

    // State
    let isPolling = false;
    let healthCheckInterval = null;

    // Initialize
    init();

    function init() {
        // Load chat history
        renderChatHistory();
        // Start health polling
        startHealthPolling();
        // Load document list
        refreshDocumentList();
        // Set up event listeners
        setupEventListeners();
    }

    function setupEventListeners() {
        // File upload
        uploadBtn.addEventListener('click', () => {
            uploadInput.click();
        });
        uploadInput.addEventListener('change', handleFileSelect);

        // Chat
        chatSend.addEventListener('click', sendChatMessage);
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendChatMessage();
            }
        });

        // Clear chat button (we'll add it to the chat input area)
        const clearBtn = document.createElement('button');
        clearBtn.id = 'clear-chat-btn';
        clearBtn.textContent = 'Clear Chat';
        clearBtn.classList.add('clear-chat-btn');
        chatInput.parentNode.insertBefore(clearBtn, chatInput.nextSibling);
        clearBtn.addEventListener('click', clearChatHistory);

        // Tab switching
        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                tabButtons.forEach(btn => btn.classList.remove('active'));
                tabContents.forEach(content => content.style.display = 'none');
                button.classList.add('active');
                const tabId = button.getAttribute('data-tab');
                document.getElementById(`${tabId}-tab`).style.display = 'block';
                // If switching to evals tab, refresh evals
                if (tabId === 'evals') {
                    refreshEvals();
                }
            });
        });
    }

    function handleFileSelect(e) {
        const files = e.target.files;
        if (files.length === 0) return;

        // Reset input
        e.target.value = '';

        // Process each file
        Array.from(files).forEach(file => {
            uploadFile(file);
        });
    }

    function uploadFile(file) {
        // Validate file type
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showUploadError(file.name, 'File is not a PDF');
            return;
        }

        // Create FormData
        const formData = new FormData();
        formData.append('file', file);

        // Show progress
        uploadProgress.innerHTML = `<div></div><p>Uploading ${file.name}...</p>`;
        const progressBar = uploadProgress.querySelector('div');
        let width = 0;
        const interval = setInterval(() => {
            if (width >= 100) {
                clearInterval(interval);
            } else {
                width++;
                progressBar.style.width = width + '%';
            }
        }, 20);

        // Upload
        fetch('/api/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                return response.text().then(text => { throw new Error(text); });
            }
            return response.json();
        })
        .then(data => {
            clearInterval(interval);
            uploadProgress.innerHTML = `<p>Upload successful!</p>`;
            // Refresh document list after a short delay
            setTimeout(() => {
                refreshDocumentList();
                // Clear progress after success
                setTimeout(() => {
                    uploadProgress.innerHTML = '';
                }, 1500);
            }, 500);
        })
        .catch(error => {
            clearInterval(interval);
            uploadProgress.innerHTML = `<p>Upload failed: ${error.message}</p>`;
            console.error('Upload error:', error);
        });
    }

    function showUploadError(filename, message) {
        uploadProgress.innerHTML = `<p>Upload failed for ${filename}: ${message}</p>`;
        setTimeout(() => {
            uploadProgress.innerHTML = '';
        }, 3000);
    }

    function sendChatMessage() {
        const message = chatInput.value.trim();
        if (message === '') return;

        // Disable input
        chatInput.disabled = true;
        chatSend.disabled = true;
        chatInput.placeholder = 'Sending...';

        // Add user message to chat
        addChatMessage(message, true);

        // Clear input
        chatInput.value = '';

        // Send to backend
        fetch('/api/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ question: message })
        })
        .then(response => {
            if (!response.ok) {
                return response.text().then(text => { throw new Error(text); });
            }
            return response.json();
        })
        .then(data => {
            // Re-enable input
            chatInput.disabled = false;
            chatSend.disabled = false;
            chatInput.placeholder = 'Ask a question about the lectures...';
            chatInput.focus();

            if (data.error) {
                // Handle error from backend
                addChatMessage(`Error: ${data.error}`, false);
            } else {
                // Add bot message with sources
                addChatMessage(data.answer, false, data.sources);
            }

            // Save to history
            saveChatHistory();
        })
        .catch(error => {
            // Re-enable input
            chatInput.disabled = false;
            chatSend.disabled = false;
            chatInput.placeholder = 'Ask a question about the lectures...';
            chatInput.focus();

            addChatMessage(`Error: ${error.message}`, false);
            saveChatHistory();
        });
    }

    function addChatMessage(content, isUser, sources = null) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message');
        messageDiv.classList.add(isUser ? 'user' : 'bot');

        if (sources && sources.length > 0) {
            // Render answer with sources
            // We'll create a div for the answer text and then a list of sources
            const answerDiv = document.createElement('div');
            answerDiv.classList.add('answer-text');
            // Escape HTML to avoid XSS
            answerDiv.textContent = content;
            messageDiv.appendChild(answerDiv);

            const sourcesDiv = document.createElement('div');
            sourcesDiv.classList.add('sources-list');
            sourcesDiv.innerHTML = '<strong>Sources:</strong>';
            const sourcesList = document.createElement('ul');
            sources.forEach(source => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${source.filename}</strong> (p. ${source.page_number})${source.section_title ? `, ${source.section_title}` : ''}`;
                sourcesList.appendChild(li);
            });
            sourcesDiv.appendChild(sourcesList);
            messageDiv.appendChild(sourcesDiv);
        } else {
            // Just the answer
            const answerDiv = document.createElement('div');
            answerDiv.classList.add('answer-text');
            answerDiv.textContent = content;
            messageDiv.appendChild(answerDiv);
        }

        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function renderChatHistory() {
        chatHistory.forEach(item => {
            addChatMessage(item.content, item.isUser, item.sources);
        });
    }

    function saveChatHistory() {
        localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(chatHistory));
    }

    function clearChatHistory() {
        if (confirm('Are you sure you want to clear the chat history?')) {
            chatHistory = [];
            localStorage.removeItem(CHAT_HISTORY_KEY);
            chatMessages.innerHTML = '';
        }
    }

    function startHealthPolling() {
        if (isPolling) return;
        isPolling = true;
        healthCheckInterval = setInterval(() => {
            checkHealth();
        }, 10000); // 10 seconds
        checkHealth(); // immediate first check
    }

    function stopHealthPolling() {
        if (!isPolling) return;
        isPolling = false;
        if (healthCheckInterval) {
            clearInterval(healthCheckInterval);
            healthCheckInterval = null;
        }
    }

    function checkHealth() {
        fetch('/api/health')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                // Update API status
                if data.llm_endpoint && data.llm_endpoint.reachable) {
                    apiStatusDot.className = 'status dot online';
                    apiStatusText.textContent = 'API: Online';
                } else {
                    apiStatusDot.className = 'status dot offline';
                    apiStatusText.textContent = 'API: Offline';
                }
                // Update DB status
                if data.database && data.database.reachable) {
                    dbStatusDot.className = 'status dot online';
                    dbStatusText.textContent = `DB: Online (${data.database.chunk_count} chunks)`;
                } else {
                    dbStatusDot.className = 'status dot offline';
                    dbStatusText.textContent = 'DB: Offline';
                }
            })
            .catch(error => {
                // Set both to offline on error
                apiStatusDot.className = 'status dot offline';
                apiStatusText.textContent = 'API: Offline';
                dbStatusDot.className = 'status dot offline';
                dbStatusText.textContent = 'DB: Offline';
                console.warn('Health check failed:', error);
            });
    }

    function refreshDocumentList() {
        fetch('/api/documents')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to fetch document list');
                }
                return response.json();
            })
            .then(data => {
                // Update the indexing info section with document list
                if (indexingInfo) {
                    if (data.files && data.files.length > 0) {
                        const listHTML = `
                            <h3>Indexed Documents (${data.total_chunks} total chunks)</h3>
                            <ul>
                                ${data.files.map(doc => `<li>${doc.filename} <span>(${doc.chunk_count} chunks)</span></li>`).join('')}
                            </li>
                            <button id="refresh-docs-btn">Refresh List</button>
                        `;
                        indexingInfo.innerHTML = listHTML;
                        // Add event listener to refresh button
                        const refreshBtn = document.getElementById('refresh-docs-btn');
                        if (refreshBtn) {
                            refreshBtn.addEventListener('click', refreshDocumentList);
                        }
                    } else {
                        indexingInfo.innerHTML = '<p>No documents indexed yet. Upload some PDFs to get started.</p>';
                    }
                }
            })
            .catch(error => {
                console.error('Error refreshing document list:', error);
                if (indexingInfo) {
                    indexingInfo.innerHTML = '<p>Error loading document list.</p>';
                }
            });
    }

    function refreshEvals() {
        fetch('/api/evals')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to fetch evals');
                }
                return response.json();
            })
            .then(data => {
                // Find the evals content area
                const evalsContent = document.getElementById('evals-content');
                if (evalsContent) {
                    if data.evals_results) {
                        // Display the results in a table
                        const results = data.evals_results;
                        let html = '<h3>Evaluation Results</h3>';
                        html += '<table><tr><th>Metric</th><th>Value</th></tr>';
                        html += `<tr><td>Dataset Size</td><td>${results.dataset_size}</td></tr>`;
                        html += `<tr><td>Top K</td><td>${results.top_k}</td></tr>`;
                        html += `<tr><td>Average Context Recall</td><td>${(results.average_context_recall * 100).toFixed(2)}%</td></tr>`;
                        html += `<tr><td>Average Faithfulness</td><td>${(results.average_faithfulness * 100).toFixed(2)}%</td></tr>`;
                        html += `<tr><td>Avg Search Latency</td><td>${results.average_latency_search_ms.toFixed(2)} ms</td></tr>`;
                        html += `<tr><td>Avg Generation Latency</td><td>${results.average_latency_generation_ms.toFixed(2)} ms</td></tr>`;
                        html += `<tr><td>Avg Total Latency</td><td>${results.average_latency_total_ms.toFixed(2)} ms</td></tr>`;
                        evalsContent.innerHTML = html;
                    } else if (data.message) {
                        evalsContent.innerHTML = `<p>${data.message}</p>`;
                    } else if (data.contents) {
                        evalsContent.innerHTML = `<p>Contents of evals directory:</p><ul>${data.contents.map(f => `<li>${f}</li>`).join('')}</ul>`;
                    } else {
                        evalsContent.innerHTML = '<p>No evaluation data available.</p>';
                    }
                }
            })
            .catch(error => {
                console.error('Error refreshing evals:', error);
                const evalsContent = document.getElementById('evals-content');
                if (evalsContent) {
                    evalsContent.innerHTML = '<p>Error loading evaluation data.</p>';
                }
            });
    }

    // Initialize the evals tab content on first load (if it's the active tab)
    // We'll do a refresh when the tab is shown, but also we can do an initial load.
    // We'll leave it to the tab switch handler.
});