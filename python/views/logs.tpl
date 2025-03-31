% include("header.tpl", title="PiFinder Logs")
<style>
  .log-container {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    padding: 15px;
    border-radius: 4px;
    height: 600px;
    overflow-y: auto;
    margin-bottom: 20px;
    position: relative;
    -webkit-overflow-scrolling: touch;
  }
  .log-line {
    margin: 0;
    white-space: pre;
    font-size: 13px;
    line-height: 1.4;
    padding: 1px 0;
    min-height: 20px;
    overflow-x: auto;
  }
  .log-content {
    width: max-content;
    min-width: 100%;
  }
  .log-line:hover {
    background-color: rgba(255, 255, 255, 0.05);
  }
  .log-line.error { color: #ff6b6b; }
  .log-line.warning { color: #ffd93d; }
  .log-line.info { color: #6bff6b; }
  .log-line.debug { color: #6b6bff; }
  .loading-message {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: #888;
    font-size: 1.2em;
  }
  .controls {
    margin-bottom: 10px;
    display: flex;
    flex-wrap: nowrap;
    gap: 10px;
    align-items: center;
  }
  .controls .btn {
    margin-right: 0;
    white-space: nowrap;
  }
  .controls select {
    height: 36px;
    margin: 0;
    padding: 0 10px;
    width: auto;
    min-width: fit-content;
  }
  .log-stats {
    color: #888;
    font-size: 0.9em;
    margin-bottom: 10px;
  }
  /* Add horizontal scrollbar styles */
  .log-container::-webkit-scrollbar,
  .log-line::-webkit-scrollbar {
    height: 8px;
    width: 8px;
  }
  .log-container::-webkit-scrollbar-track,
  .log-line::-webkit-scrollbar-track {
    background: #2e2e2e;
  }
  .log-container::-webkit-scrollbar-thumb,
  .log-line::-webkit-scrollbar-thumb {
    background: #666;
    border-radius: 4px;
  }
  .log-container::-webkit-scrollbar-thumb:hover,
  .log-line::-webkit-scrollbar-thumb:hover {
    background: #888;
  }
  @media (max-width: 600px) {
    .controls {
      flex-direction: column;
    }
    .controls .btn {
      width: 100%;
      margin-bottom: 5px;
    }
    .log-line {
      font-size: 11px;
    }
  }
</style>

<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
    <h5 class="grey-text">PiFinder Logs</h5>
  </div>
</div>

<div class="card grey darken-2">
  <div class="card-content">
    <div class="row">
      <div class="col s12">
        <div class="controls">
          <button id="downloadButton" class="btn">
            <i class="material-icons left">download</i>Download All Logs
          </button>
          <button id="pauseButton" class="btn">
            <i class="material-icons left">pause</i>Pause
          </button>
          <button id="restartFromCurrent" class="btn" style="display: none;">
            <i class="material-icons left">play_arrow</i>Resume from Current
          </button>
          <button id="restartFromEnd" class="btn" style="display: none;">
            <i class="material-icons left">replay</i>Restart from End
          </button>
          <button id="copyButton" class="btn">
            <i class="material-icons left">content_copy</i>Copy to Clipboard
          </button>
          <select id="globalLevel" class="browser-default">
            <option value="DEBUG">Global: Debug</option>
            <option value="INFO">Global: Info</option>
            <option value="WARNING">Global: Warning</option>
            <option value="ERROR">Global: Error</option>
          </select>
          <select id="componentSelect" class="browser-default">
            <option value="" disabled selected>Select Component</option>
          </select>
          <select id="componentLevel" class="browser-default" style="display: none;">
            <option value="DEBUG">Debug</option>
            <option value="INFO">Info</option>
            <option value="WARNING">Warning</option>
            <option value="ERROR">Error</option>
          </select>
        </div>
        <div class="log-stats">
          Total lines: <span id="totalLines">0</span>
        </div>
      </div>
    </div>

    <div class="row">
      <div class="col s12">
        <div class="log-container" id="logViewer">
          <div id="loadingMessage" class="loading-message">Loading log files...</div>
          <div id="logContent" class="log-content"></div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
let currentPosition = 0;
let isPaused = false;
let logBuffer = [];
const BUFFER_SIZE = 100;
const LINE_HEIGHT = 20;
let updateInterval;
let lastLine = '';

function fetchLogs() {
    if (isPaused) return;
    
    fetch(`/logs/stream?position=${currentPosition}`)
        .then(response => response.json())
        .then(data => {
            if (!data.logs || data.logs.length === 0) return;
            
            currentPosition = data.position;
            const logContent = document.getElementById('logContent');
            
            // Add new logs to buffer, skipping duplicates
            data.logs.forEach(line => {
                if (line !== lastLine) {
                    logBuffer.push(line);
                    lastLine = line;
                }
            });
            
            // Trim buffer if it exceeds size
            if (logBuffer.length > BUFFER_SIZE) {
                logBuffer = logBuffer.slice(-BUFFER_SIZE);
            }
            
            // Update display
            updateLogDisplay();
        })
        .catch(error => console.error('Error fetching logs:', error));
}

function updateLogDisplay() {
    const logContent = document.getElementById('logContent');
    logContent.innerHTML = '';
    
    logBuffer.forEach(line => {
        const logLine = document.createElement('div');
        logLine.style.height = `${LINE_HEIGHT}px`;
        logLine.style.whiteSpace = 'pre';
        logLine.textContent = line;
        
        // Add color based on log level
        if (line.includes('ERROR')) {
            logLine.style.color = '#ff6b6b';
        } else if (line.includes('WARNING')) {
            logLine.style.color = '#ffd93d';
        } else if (line.includes('INFO')) {
            logLine.style.color = '#6bff6b';
        } else if (line.includes('DEBUG')) {
            logLine.style.color = '#6b6bff';
        }
        
        logContent.appendChild(logLine);
    });
    
    // Auto-scroll if not paused
    if (!isPaused) {
        logContent.scrollTop = logContent.scrollHeight;
    }
}

function togglePause() {
    isPaused = !isPaused;
    const pauseButton = document.getElementById('pauseButton');
    pauseButton.textContent = isPaused ? 'Resume' : 'Pause';
    
    if (!isPaused) {
        // Resume fetching from last position
        fetchLogs();
    }
}

function restartFromEnd() {
    currentPosition = 0;
    logBuffer = [];
    isPaused = false;
    document.getElementById('pauseButton').textContent = 'Pause';
    fetchLogs();
}

// Start fetching logs when page loads
document.addEventListener('DOMContentLoaded', () => {
    // Show loading message
    const loadingMessage = document.querySelector('.loading-message');
    loadingMessage.style.display = 'flex';
    
    // Start log fetching
    fetchLogs();
    updateInterval = setInterval(fetchLogs, 1000);
    
    // Hide loading message after first logs appear
    const observer = new MutationObserver((mutations) => {
        if (document.getElementById('logContent').textContent.trim()) {
            loadingMessage.style.display = 'none';
            observer.disconnect();
        }
    });
    
    observer.observe(document.getElementById('logContent'), {
        childList: true,
        subtree: true,
        characterData: true
    });

    // Load component levels
    updateComponentLevels();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    clearInterval(updateInterval);
});

// Add copy to clipboard functionality
document.getElementById('copyButton').addEventListener('click', function() {
    const logContent = document.getElementById('logContent');
    const text = logContent.innerText;
    
    navigator.clipboard.writeText(text).then(() => {
        // Visual feedback
        const originalText = this.innerHTML;
        this.innerHTML = '<i class="material-icons left">check</i>Copied!';
        setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy text: ', err);
        // Visual feedback for error
        const originalText = this.innerHTML;
        this.innerHTML = '<i class="material-icons left">error</i>Failed to copy';
        setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    });
});

// Log level management
function updateComponentLevels() {
    fetch('/logs/components')
        .then(response => response.json())
        .then(data => {
            const componentSelect = document.getElementById('componentSelect');
            componentSelect.innerHTML = '<option value="" disabled selected>Select Component</option>';
            
            // Sort components alphabetically
            const sortedComponents = Object.entries(data.components).sort(([a], [b]) => a.localeCompare(b));
            
            sortedComponents.forEach(([component, levels]) => {
                const option = document.createElement('option');
                option.value = component;
                option.textContent = component;
                componentSelect.appendChild(option);
            });
        })
        .catch(error => console.error('Error fetching component levels:', error));
}

// Handle global level change
document.getElementById('globalLevel').addEventListener('change', function(e) {
    const newLevel = e.target.value;
    fetch('/logs/level', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `level=${encodeURIComponent(newLevel)}`
    })
    .then(response => response.json())
    .then(result => {
        if (result.status === 'success') {
            console.log(`Changed global log level to ${newLevel}`);
        } else {
            console.error('Failed to update global log level:', result.message);
        }
    })
    .catch(error => console.error('Error updating global log level:', error));
});

// Handle component selection
document.getElementById('componentSelect').addEventListener('change', function(e) {
    const component = e.target.value;
    if (!component) {
        document.getElementById('componentLevel').style.display = 'none';
        return;
    }
    
    // Show level select and set current level
    const levelSelect = document.getElementById('componentLevel');
    levelSelect.style.display = 'block';
    
    // Get current level for selected component
    fetch('/logs/components')
        .then(response => response.json())
        .then(data => {
            const currentLevel = data.components[component].current_level;
            levelSelect.value = currentLevel;
        });
});

// Handle component level change
document.getElementById('componentLevel').addEventListener('change', function(e) {
    const component = document.getElementById('componentSelect').value;
    const newLevel = e.target.value;
    
    fetch('/logs/component_level', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `component=${encodeURIComponent(component)}&level=${encodeURIComponent(newLevel)}`
    })
    .then(response => response.json())
    .then(result => {
        if (result.status === 'success') {
            console.log(`Changed ${component} log level to ${newLevel}`);
        } else {
            console.error('Failed to update log level:', result.message);
        }
    })
    .catch(error => console.error('Error updating log level:', error));
});

// Initial load of components
updateComponentLevels();

// Set up button event listeners
document.getElementById('pauseButton').addEventListener('click', function() {
    if (isPaused) {
        togglePause();
    } else {
        togglePause();
    }
});

document.getElementById('restartFromCurrent').addEventListener('click', function() {
    togglePause();
});

document.getElementById('restartFromEnd').addEventListener('click', function() {
    restartFromEnd();
});
</script>

% include("footer.tpl") 