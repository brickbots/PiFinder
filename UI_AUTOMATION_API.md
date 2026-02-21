# PiFinder UI Automation API

## Overview

The PiFinder web server includes UI automation API endpoints to enable automated testing and iteration workflows. These endpoints allow Claude Code (or any automation tool) to:

1. Take screenshots of the current UI state
2. Navigate to specific menu locations  
3. Execute key sequences
4. Get the menu structure

## API Endpoints

### 1. Consolidated Screenshot API

**Endpoint:** `GET /api/screenshot` or `POST /api/screenshot`

The single endpoint for all screenshot and navigation needs - always returns a screenshot at native resolution.

#### GET Request (Simple)
**Parameters:**
- `path` (optional): Menu path like "settings/display"
- `format` (optional): "png" or "jpeg" (default: jpeg)

**Examples:**
```bash
# Basic screenshot
curl "http://pifinder.local/api/screenshot"

# Navigate to menu path then screenshot
curl "http://pifinder.local/api/screenshot?path=settings/display"

# PNG format
curl "http://pifinder.local/api/screenshot?format=png"
```

#### POST Request (Advanced)
**Content-Type:** `application/json`

**Body:**
```json
{
  "path": "settings/display",        // optional menu path
  "keys": ["UP", "DOWN", "A"],      // optional key sequence  
  "format": "jpeg"                   // optional format
}
```

**Available Keys:**
- Direction: `"UP"`, `"DN"`, `"A"`, `"B"`, `"C"`, `"D"`
- Special: `"SQUARE"`, `"ALT_PLUS"`, `"ALT_MINUS"`, `"ALT_LEFT"`, etc.
- Numbers: `0-9` (as integers)

**Examples:**
```bash
# Navigate to path then execute keys
curl -X POST "http://pifinder.local/api/screenshot" \
  -H "Content-Type: application/json" \
  -d '{"path": "settings", "keys": ["DOWN", "DOWN", "A"]}'

# Execute key sequence only
curl -X POST "http://pifinder.local/api/screenshot" \
  -H "Content-Type: application/json" \
  -d '{"keys": ["SQUARE", "UP", "A"]}'
```

### 2. Menu Structure API

**Endpoint:** `GET /api/menu-structure`

Returns the complete menu structure as JSON, including current UI stack state.

**Example:**
```bash
curl "http://pifinder.local/api/menu-structure"
```

## Authentication

All API endpoints require authentication using the same cookie-based system as the web interface. You'll need to:

1. First login at `/login` with the PiFinder password
2. Use the session cookie for subsequent API calls

## Usage Workflow for Claude Code

### Typical Automation Flow:

1. **Make code changes** to PiFinder UI components
2. **Start the PiFinder app** 
3. **Take initial screenshot:**
   ```bash
   curl "http://pifinder.local/api/screenshot" > current_ui.jpg
   ```
4. **Navigate to specific screen:**
   ```bash
   curl -X POST "http://pifinder.local/api/screenshot" \
     -H "Content-Type: application/json" \
     -d '{"path": "settings/display"}' > settings_screen.jpg
   ```
5. **Test specific interactions:**
   ```bash
   curl -X POST "http://pifinder.local/api/screenshot" \
     -H "Content-Type: application/json" \
     -d '{"keys": ["DOWN", "A", "SQUARE"]}' > interaction_result.jpg
   ```
6. **Iterate based on visual feedback**

### Advanced Usage:

**Get menu structure first:**
```bash
curl "http://pifinder.local/api/menu-structure" | jq .
```

**Complex navigation and testing:**
```bash
curl -X POST "http://pifinder.local/api/screenshot" \
  -H "Content-Type: application/json" \
  -d '{"path": "objects", "keys": ["DOWN", "DOWN", "A", "1", "2", "3"]}' > test_result.jpg
```

## Key Advantages

- **Single Endpoint**: One `/api/screenshot` handles all use cases
- **Always Returns Image**: Every operation ends with visual feedback
- **Native Resolution**: No scaling - returns actual display resolution
- **Flexible Navigation**: Supports both path-based and key-sequence navigation
- **Format Options**: PNG for exact pixels, JPEG for smaller files

## Integration with Playwright MCP

This API works perfectly with Claude Code's Playwright MCP for visual UI testing:

```javascript
// Take screenshot and analyze with Claude Code
const response = await fetch('http://pifinder.local/api/screenshot', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({"path": "radec_entry", "keys": ["SQUARE"]})
});
const imageBuffer = await response.buffer();
// Use mcp__playwright tools to analyze the image
```

This consolidated approach eliminates API redundancy while providing all the functionality needed for comprehensive UI automation and testing workflows.