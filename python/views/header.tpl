<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="/static/styles.css" />
<title>PiFinder - {{title}}</title>
</head>
<body>
    <label class="hamburger-menu">
      <input type="checkbox" />
    </label>
    <aside class="sidebar">
      <nav>
        <div class="sidebar-item" onClick="location.href='/';">Home</div>
        <div class="sidebar-item" onClick="location.href='/remote';">Remote</div>
        <div class="sidebar-item" onCLick="location.href='/status';">Status</div>
        <div class="sidebar-item" onCLick="location.href='/options';">Options</div>
        <div class="sidebar-item" onCLick="location.href='/network';">Network</div>
      </nav>
    </aside>
    <div class="header">
        <img src="/images/WebLogo_RED.png" height=50px>
    </div>
    <div class="main-body-container">
