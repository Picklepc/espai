/**
 * ESPAI Provisioning Firmware
 *
 * First-boot experience for ESP32 devices entering the ESPAI ecosystem.
 * Hosts a retro-themed web portal in WiFi AP mode — no app, no cloud,
 * no setup tool required.  Just power on, connect, configure.
 *
 * AP always-on:  SSID = ESPAI-Setup   Pass = espai1234   IP = 192.168.4.1
 * STA+AP mode:   after home WiFi is configured, both run simultaneously.
 *
 * Portal features:
 *   - Board statistics (chip, MAC, node ID, heap, uptime, IPs)
 *   - WiFi scan + connect
 *   - ESPAI Hub URL save / test / checkin
 *   - OTA firmware upload with progress (replaces this firmware)
 *   - ESPAI intro, demo descriptions, what's-next onboarding guide
 *
 * Flash:  pio run -e esp32dev --target upload
 * Serial: pio device monitor --baud 115200
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ESPmDNS.h>
#include <Update.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <esp_wifi.h>
#include <mbedtls/md.h>

// ── Build-flag defaults ────────────────────────────────────────────────────
#ifndef FW_VERSION
#define FW_VERSION "1.0.0"
#endif
#ifndef FW_NAME
#define FW_NAME "ESPAI-Provision"
#endif

// ── AP credentials ─────────────────────────────────────────────────────────
#define AP_SSID "ESPAI-Setup"
#define AP_PASS "espai1234"

// ── Globals ────────────────────────────────────────────────────────────────
WebServer   server(80);
Preferences prefs;

String g_nodeId;
String g_staSSID;
String g_staPass;
String g_hubUrl;
bool   g_staConnected = false;
bool   g_otaError     = false;

// ═══════════════════════════════════════════════════════════════════════════
//  WEB PORTAL  (single-file, PROGMEM-embedded, no LittleFS needed)
// ═══════════════════════════════════════════════════════════════════════════

static const char PAGE_HTML[] PROGMEM = R"espai_html(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ESPAI — Provisioning</title>
<style>
:root{--bg:#080c10;--surface:#0d1824;--card:#121f30;--border:#1c3650;--text:#eeddc4;--muted:#7a9aaa;--accent:#1aafc4;--accent2:#e07828;--gold:#f0a820;--danger:#e03248;--success:#20bf96;--r:10px}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;font-size:15px;line-height:1.5;min-height:100vh;overflow-x:hidden}

/* retro perspective grid */
body::before{content:'';position:fixed;bottom:0;left:0;right:0;height:48vh;
  background:linear-gradient(rgba(26,175,196,.13) 1px,transparent 1px) 0 0/50px 50px,
             linear-gradient(90deg,rgba(26,175,196,.13) 1px,transparent 1px) 0 0/50px 50px;
  transform:perspective(280px) rotateX(38deg);transform-origin:50% 100%;
  pointer-events:none;z-index:0;
  mask-image:linear-gradient(to top,black 0%,transparent 100%);
  -webkit-mask-image:linear-gradient(to top,black 0%,transparent 100%)}

/* scanlines */
body::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:9999;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,0,0,.05) 3px,rgba(0,0,0,.05) 4px)}

.wrap{max-width:920px;margin:0 auto;padding:0 18px 100px;position:relative;z-index:1}

/* ── Header ── */
header{display:flex;align-items:center;justify-content:space-between;padding:22px 0 16px;border-bottom:1px solid var(--border);margin-bottom:30px;flex-wrap:wrap;gap:12px}
.logo-row{display:flex;align-items:center;gap:14px}
.logo-label{display:flex;flex-direction:column;gap:2px}
.logo-name{font-size:22px;font-weight:900;letter-spacing:3px;color:var(--text)}
.logo-sub{font-size:9px;font-weight:700;letter-spacing:2.5px;color:var(--accent2);text-transform:uppercase}
.hdr-right{text-align:right}
.node-id{font-size:12px;font-family:monospace;color:var(--accent);letter-spacing:.5px}
.wifi-dot{font-size:11px;color:var(--muted);margin-top:3px}

/* ── Hero ── */
.hero{text-align:center;padding:36px 16px 44px}
.hero h1{font-size:clamp(36px,8vw,58px);font-weight:900;letter-spacing:5px;color:var(--text);margin-bottom:10px;text-shadow:0 0 48px rgba(240,168,32,.28)}
.hero h1 span{color:var(--accent2)}
.hero .sub{color:var(--muted);font-size:14px;max-width:520px;margin:6px auto}
.hero .tagline{font-size:11px;font-weight:700;letter-spacing:3px;color:var(--accent);text-transform:uppercase;margin-top:18px}

/* step pills */
.steps{display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin-top:22px}
.step{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:5px 12px;transition:.2s}
.step-n{width:18px;height:18px;border-radius:50%;background:var(--border);color:var(--muted);font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center;transition:.2s}
.step.active{border-color:var(--accent);color:var(--text)}
.step.active .step-n{background:var(--accent);color:var(--bg)}
.step.done{border-color:var(--success)}
.step.done .step-n{background:var(--success);color:var(--bg)}

/* ── Cards ── */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:20px;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.55}
.card.gold::before{background:linear-gradient(90deg,transparent,var(--gold),transparent)}
.card.orange::before{background:linear-gradient(90deg,transparent,var(--accent2),transparent)}
.card.green::before{background:linear-gradient(90deg,transparent,var(--success),transparent)}
.card.full{grid-column:1/-1}

.card-title{font-size:10px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--accent);margin-bottom:14px;display:flex;align-items:center;gap:7px}
.card.gold .card-title{color:var(--gold)}
.card.orange .card-title{color:var(--accent2)}
.card.green .card-title{color:var(--success)}

/* stat grid */
.sg{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-bottom:14px}
.si{background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:9px 11px}
.sl{font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px}
.sv{font-family:monospace;font-size:12px;color:var(--text);word-break:break-all}
.sv.a{color:var(--accent)} .sv.g{color:var(--gold)} .sv.ok{color:var(--success)}

/* form */
.fg{margin-bottom:13px}
label{display:block;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:5px}
input[type=text],input[type=password],input[type=url]{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 11px;color:var(--text);font-size:14px;font-family:inherit;outline:none;transition:.15s}
input:focus{border-color:var(--accent)}

/* network list */
.net-list{display:flex;flex-direction:column;gap:5px;max-height:170px;overflow-y:auto;margin-bottom:12px}
.net-item{display:flex;align-items:center;justify-content:space-between;padding:7px 11px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:13px;transition:.15s}
.net-item:hover,.net-item.sel{border-color:var(--accent);background:rgba(26,175,196,.07)}
.net-rssi{font-size:11px;color:var(--muted);white-space:nowrap}

/* buttons */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 16px;border:none;border-radius:6px;font-size:13px;font-weight:700;font-family:inherit;letter-spacing:.4px;cursor:pointer;transition:opacity .15s,transform .1s}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.bp{background:var(--accent);color:var(--bg)}
.bs{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.bo{background:var(--accent2);color:var(--bg)}
.bg_{background:var(--gold);color:var(--bg)}
.bd{background:var(--danger);color:#fff}
.bsm{padding:5px 11px;font-size:12px}
.btn-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}

/* alerts */
.alert{padding:9px 13px;border-radius:7px;font-size:13px;margin-top:11px}
.ok{background:rgba(32,191,150,.1);border:1px solid rgba(32,191,150,.3);color:var(--success)}
.err{background:rgba(224,50,72,.1);border:1px solid rgba(224,50,72,.3);color:var(--danger)}
.inf{background:rgba(26,175,196,.1);border:1px solid rgba(26,175,196,.3);color:var(--accent)}
.warn{background:rgba(240,168,32,.1);border:1px solid rgba(240,168,32,.3);color:var(--gold)}
.hidden{display:none!important}

/* progress */
.pw{background:var(--surface);border:1px solid var(--border);border-radius:6px;height:9px;overflow:hidden;margin:9px 0}
.pb{height:100%;background:linear-gradient(90deg,var(--accent2),var(--accent));width:0%;transition:width .3s}

/* drop zone */
.dz{border:2px dashed var(--border);border-radius:8px;padding:22px;text-align:center;cursor:pointer;transition:.2s;color:var(--muted);font-size:13px}
.dz:hover,.dz.drag{border-color:var(--accent);background:rgba(26,175,196,.05);color:var(--text)}
.dz-icon{font-size:26px;margin-bottom:7px}

/* checklist */
.cl{display:flex;flex-direction:column;gap:14px}
.ci{display:flex;gap:13px;align-items:flex-start}
.cn{flex-shrink:0;width:24px;height:24px;border-radius:50%;background:var(--surface);border:2px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:var(--muted);margin-top:1px;transition:.2s}
.cn.done{background:var(--success);border-color:var(--success);color:var(--bg)}
.cn.act{border-color:var(--accent);color:var(--accent)}
.cb h4{font-size:14px;font-weight:700;color:var(--text);margin-bottom:3px}
.cb p{font-size:12px;color:var(--muted);line-height:1.7}
code{background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:1px 5px;font-size:11px;font-family:monospace;color:var(--accent)}

/* demo feature items */
.fi{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:11px}
.fitem{background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:13px}
.fitem strong{color:var(--accent2);font-size:13px;display:block;margin-bottom:5px}
.fitem p{font-size:12px;color:var(--muted);line-height:1.6}

/* info box */
.ib{background:rgba(240,168,32,.07);border:1px solid rgba(240,168,32,.22);border-radius:7px;padding:11px 13px;font-size:13px;margin-bottom:13px}
.ib-label{font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--gold);margin-bottom:4px}

/* footer */
footer{text-align:center;padding:44px 16px 24px;color:var(--muted);font-size:11px;letter-spacing:1px;position:relative;z-index:1}
footer .ft{font-weight:700;color:var(--accent2);letter-spacing:3px;font-size:10px;text-transform:uppercase;margin-bottom:5px}
</style>
</head>
<body>
<div class="wrap">

<!-- ── Header ── -->
<header>
  <div class="logo-row">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="52" height="52" aria-hidden="true">
      <defs>
        <clipPath id="pc"><rect x="39" y="39" width="122" height="122" rx="19" transform="rotate(45 100 100)"/></clipPath>
        <radialGradient id="ps" cx="50%" cy="100%" r="70%">
          <stop offset="0%" stop-color="#f07020"/><stop offset="45%" stop-color="#cc3820"/>
          <stop offset="80%" stop-color="#8a1010"/><stop offset="100%" stop-color="#4a0808"/>
        </radialGradient>
        <radialGradient id="pb" cx="50%" cy="35%" r="75%">
          <stop offset="0%" stop-color="#101c2a"/><stop offset="100%" stop-color="#060a10"/>
        </radialGradient>
      </defs>
      <rect x="33" y="33" width="134" height="134" rx="22" transform="rotate(45 100 100)" fill="none" stroke="#1aafc4" stroke-width="3"/>
      <rect x="38" y="38" width="124" height="124" rx="20" transform="rotate(45 100 100)" fill="url(#pb)" stroke="#eeddc4" stroke-width="1.2" opacity=".85"/>
      <g clip-path="url(#pc)">
        <circle cx="52" cy="50" r="1" fill="#eeddc4" opacity=".7"/>
        <circle cx="148" cy="45" r=".9" fill="#eeddc4" opacity=".6"/>
        <circle cx="162" cy="74" r=".8" fill="#eeddc4" opacity=".5"/>
        <circle cx="38" cy="84" r=".8" fill="#eeddc4" opacity=".5"/>
        <circle cx="155" cy="142" r=".7" fill="#eeddc4" opacity=".35"/>
        <rect x="0" y="122" width="200" height="80" fill="#050810"/>
        <line x1="0" y1="128" x2="200" y2="128" stroke="#1aafc4" stroke-width="1.1" opacity=".8"/>
        <line x1="0" y1="138" x2="200" y2="138" stroke="#1aafc4" stroke-width=".85" opacity=".65"/>
        <line x1="0" y1="149" x2="200" y2="149" stroke="#1aafc4" stroke-width=".65" opacity=".5"/>
        <line x1="0" y1="162" x2="200" y2="162" stroke="#1aafc4" stroke-width=".5" opacity=".4"/>
        <line x1="100" y1="128" x2="0" y2="200" stroke="#1aafc4" stroke-width=".9" opacity=".65"/>
        <line x1="100" y1="128" x2="200" y2="200" stroke="#1aafc4" stroke-width=".9" opacity=".65"/>
        <line x1="100" y1="128" x2="28" y2="200" stroke="#1aafc4" stroke-width=".7" opacity=".5"/>
        <line x1="100" y1="128" x2="172" y2="200" stroke="#1aafc4" stroke-width=".7" opacity=".5"/>
        <ellipse cx="100" cy="128" rx="58" ry="32" fill="url(#ps)" opacity=".98"/>
        <ellipse cx="100" cy="128" rx="42" ry="22" fill="#cc3020" opacity=".5"/>
        <rect x="42" y="122" width="116" height="2.5" fill="#060a10" opacity=".55"/>
        <rect x="42" y="116" width="116" height="2" fill="#060a10" opacity=".44"/>
        <rect x="42" y="110" width="116" height="1.8" fill="#060a10" opacity=".36"/>
      </g>
      <path d="M100 20 L101.2 31 L107 34 L101.2 37 L100 48 L98.8 37 L93 34 L98.8 31 Z" fill="#f0a820"/>
      <text x="100" y="92" text-anchor="middle" font-family="Arial Black,sans-serif" font-weight="900" font-size="38" fill="#eeddc4" letter-spacing="4">ESPAI</text>
    </svg>
    <div class="logo-label">
      <div class="logo-name">ESPAI</div>
      <div class="logo-sub">Provisioning Firmware v<span id="hVer">—</span></div>
    </div>
  </div>
  <div class="hdr-right">
    <div class="node-id" id="hNodeId">Connecting…</div>
    <div class="wifi-dot" id="hWifi">⬤ AP mode</div>
  </div>
</header>

<!-- ── Hero ── -->
<section class="hero">
  <h1>HELLO <span>WORLD.</span></h1>
  <p class="sub">You're running <strong>ESPAI Provisioning Firmware</strong> — your launchpad into the ESPAI ecosystem. Configure WiFi, connect to your hub, and flash your first real project.</p>
  <p class="tagline">▸ YOUR LAB. YOUR RULES.</p>
  <div class="steps">
    <div class="step" id="st1"><div class="step-n">1</div> Connect WiFi</div>
    <div class="step" id="st2"><div class="step-n">2</div> Set Hub URL</div>
    <div class="step" id="st3"><div class="step-n">3</div> Pair Device</div>
    <div class="step" id="st4"><div class="step-n">4</div> Flash Project</div>
  </div>
</section>

<!-- ── Cards ── -->
<div class="cards">

  <!-- Board Stats -->
  <div class="card gold">
    <div class="card-title">◈ Board Statistics</div>
    <div class="sg">
      <div class="si"><div class="sl">Node ID</div><div class="sv a" id="sNid">—</div></div>
      <div class="si"><div class="sl">MAC Address</div><div class="sv" id="sMac">—</div></div>
      <div class="si"><div class="sl">Chip Model</div><div class="sv" id="sChip">—</div></div>
      <div class="si"><div class="sl">CPU / Flash</div><div class="sv" id="sCpu">—</div></div>
      <div class="si"><div class="sl">Free Heap</div><div class="sv g" id="sHeap">—</div></div>
      <div class="si"><div class="sl">Uptime</div><div class="sv" id="sUp">—</div></div>
      <div class="si"><div class="sl">AP IP</div><div class="sv a" id="sApIp">—</div></div>
      <div class="si"><div class="sl">STA IP</div><div class="sv" id="sStaIp">—</div></div>
      <div class="si"><div class="sl">Hostname</div><div class="sv" id="sHost">—</div></div>
      <div class="si"><div class="sl">Signal (RSSI)</div><div class="sv" id="sRssi">—</div></div>
    </div>
    <div class="btn-row">
      <button class="btn bs bsm" onclick="loadStats()">↻ Refresh</button>
      <button class="btn bs bsm" onclick="reboot()">⟳ Reboot</button>
    </div>
  </div>

  <!-- WiFi -->
  <div class="card">
    <div class="card-title">◉ WiFi Configuration</div>
    <div class="ib">
      <div class="ib-label">▸ You are connected to this device's AP</div>
      SSID: <strong>ESPAI-Setup</strong> &nbsp;·&nbsp; Pass: <strong>espai1234</strong><br>
      Connect to your home WiFi below — AP stays active so you keep access.
    </div>
    <label>Nearby Networks <button class="btn bs bsm" style="float:right;margin-top:-4px" onclick="scanWifi()">⊕ Scan</button></label>
    <div class="net-list" id="netList"><div style="color:var(--muted);font-size:12px;padding:6px">Press Scan to discover networks</div></div>
    <div class="fg">
      <label>SSID</label>
      <input type="text" id="wSSID" placeholder="MyHomeNetwork">
    </div>
    <div class="fg">
      <label>Password</label>
      <input type="password" id="wPass" placeholder="•••••••">
    </div>
    <div id="wAlert" class="alert hidden"></div>
    <div class="btn-row">
      <button class="btn bp" id="btnConn" onclick="connectWifi()">Connect</button>
      <button class="btn bs bsm" onclick="disconnectWifi()">Disconnect</button>
    </div>
  </div>

  <!-- Hub Connect -->
  <div class="card orange">
    <div class="card-title">◎ ESPAI Hub Connection</div>
    <p style="font-size:13px;color:var(--muted);margin-bottom:14px">
      ESPAI Hub runs on your computer and manages your entire device fleet.
      Once you're on home WiFi, enter your hub's address below.
    </p>
    <div class="fg">
      <label>Hub URL</label>
      <input type="url" id="hubUrl" placeholder="http://192.168.1.100:7888">
    </div>
    <div id="hubAlert" class="alert hidden"></div>
    <div class="btn-row">
      <button class="btn bo" onclick="saveHub()">Save</button>
      <button class="btn bs bsm" onclick="testHub()">⊙ Test</button>
      <button class="btn bs bsm" onclick="checkinHub()">→ Check In</button>
    </div>
    <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border);font-size:12px;color:var(--muted);line-height:1.8">
      <strong style="color:var(--accent2)">Install ESPAI Hub:</strong><br>
      Clone the repo → <code>python espai.py serve</code> → open <code>localhost:7888</code><br>
      This device appears in Fleet automatically once on the same network.
    </div>
  </div>

  <!-- Firmware Update -->
  <div class="card">
    <div class="card-title">▲ Firmware Update</div>
    <div class="sg" style="margin-bottom:14px">
      <div class="si"><div class="sl">Firmware</div><div class="sv a" id="sFwName">ESPAI-Provision</div></div>
      <div class="si"><div class="sl">Version</div><div class="sv" id="sFwVer">—</div></div>
    </div>
    <label>Upload New Firmware (.bin)</label>
    <div class="dz" id="dz" onclick="document.getElementById('fwf').click()">
      <div class="dz-icon">↑</div>
      <div>Drop <code>.bin</code> here or <strong>click to browse</strong></div>
      <div style="font-size:11px;margin-top:4px;color:var(--muted)" id="dzName">No file selected</div>
    </div>
    <input type="file" id="fwf" accept=".bin" style="display:none" onchange="onFile(this)">
    <div class="pw hidden" id="fwProg"><div class="pb" id="fwBar"></div></div>
    <div id="fwAlert" class="alert hidden"></div>
    <div class="btn-row">
      <button class="btn bp" id="btnFlash" onclick="flash()" disabled>⚡ Flash Firmware</button>
    </div>
    <p style="font-size:11px;color:var(--muted);margin-top:10px">
      ⚠ The device reboots after flashing. Reconnect to ESPAI-Setup (AP stays active after rebooting into your new firmware if it supports AP mode).
    </p>
  </div>

  <!-- What is ESPAI — full width -->
  <div class="card full gold">
    <div class="card-title">★ What is ESPAI?</div>
    <div class="fi">
      <div class="fitem"><strong>Fleet Management</strong><p>Monitor hundreds of ESP32s from one dashboard. See status, heap, uptime, IP — all in real time.</p></div>
      <div class="fitem"><strong>Wireless OTA Updates</strong><p>Compile with PlatformIO, upload the .bin to the hub catalog, push to any paired device over WiFi.</p></div>
      <div class="fitem"><strong>Event Rules Engine</strong><p>When a device publishes an event, fire a Python worker, POST a webhook, or log it automatically.</p></div>
      <div class="fitem"><strong>Recipe &amp; Worker System</strong><p>Define reusable behaviours as YAML recipes. Run Python workers for data pipelines, ML inference, control loops.</p></div>
      <div class="fitem"><strong>Auto-Discovery</strong><p>mDNS + LAN scan finds devices the moment they power on. No static IPs, no manual registration.</p></div>
      <div class="fitem"><strong>100% Local-First</strong><p>No cloud. No subscriptions. No telemetry. Runs on your machine, on your network. Your lab, your rules.</p></div>
    </div>
  </div>

  <!-- What's Next — full width -->
  <div class="card full green">
    <div class="card-title">▶ What's Next — Your Launch Sequence</div>
    <div class="cl">
      <div class="ci">
        <div class="cn" id="cn1">1</div>
        <div class="cb">
          <h4>Connect this device to your home WiFi</h4>
          <p>Use the WiFi Configuration card. The device joins in STA+AP mode — you keep portal access via <code>192.168.4.1</code> while it connects to your network.</p>
        </div>
      </div>
      <div class="ci">
        <div class="cn" id="cn2">2</div>
        <div class="cb">
          <h4>Install and start ESPAI Hub on your computer</h4>
          <p>Clone the repo, run <code>python espai.py install-deps</code> then <code>python espai.py serve</code>. Dashboard opens at <code>localhost:7888</code>.</p>
        </div>
      </div>
      <div class="ci">
        <div class="cn" id="cn3">3</div>
        <div class="cb">
          <h4>Enter your hub URL and check in</h4>
          <p>Fill in the Hub Connection card above with your computer's IP, e.g. <code>http://192.168.1.50:7888</code>. Hit <strong>Check In</strong> — this device appears in Fleet instantly.</p>
        </div>
      </div>
      <div class="ci">
        <div class="cn" id="cn4">4</div>
        <div class="cb">
          <h4>Pair the device in Fleet view</h4>
          <p>Click <strong>Pair</strong> on this device's card in the hub dashboard. A token is generated and confirmed — device is now authorized for OTA updates.</p>
        </div>
      </div>
      <div class="ci">
        <div class="cn" id="cn5">5</div>
        <div class="cb">
          <h4>Create your first project and flash real firmware</h4>
          <p>Hub → <strong>Projects → New Project</strong> → generates a PlatformIO scaffold. Add your sensor/actuator code, build with <code>pio run</code>, upload the <code>.bin</code> via the hub OTA catalog or directly from this page, and push wirelessly.</p>
        </div>
      </div>
    </div>
  </div>

</div><!-- /cards -->
</div><!-- /wrap -->

<footer>
  <div class="ft">YOUR LAB. YOUR RULES.</div>
  <div>ESPAI Provisioning &nbsp;·&nbsp; <span id="fNid">—</span> &nbsp;·&nbsp; v<span id="fVer">—</span></div>
</footer>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let stats={}, fwFile=null;

// ── Boot ───────────────────────────────────────────────────────────────────
(async()=>{
  await loadStats();
  setInterval(loadStats,10000);
  setupDrop();
})();

// ── Stats ──────────────────────────────────────────────────────────────────
async function loadStats(){
  try{
    const r=await fetch('/api/stats'); stats=await r.json();
    const T=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v||'—'};
    T('hNodeId',stats.node_id); T('hVer',stats.fw_version);
    T('sNid',stats.node_id); T('sMac',stats.mac);
    T('sChip',stats.chip_model+' ×'+stats.chip_cores+' cores');
    T('sCpu',stats.chip_freq_mhz+' MHz · '+stats.flash_mb+' MB flash');
    T('sHeap',(stats.free_heap/1024).toFixed(1)+' KB / '+(stats.heap_size/1024).toFixed(1)+' KB');
    T('sUp',fmtUp(stats.uptime_s));
    T('sApIp',stats.ap_ip); T('sStaIp',stats.sta_ip||'Not connected');
    T('sHost',stats.hostname);
    T('sRssi',stats.sta_connected?stats.sta_rssi+' dBm':'—');
    T('sFwVer',stats.fw_version); T('sFwName',stats.fw_name);
    T('fNid',stats.node_id); T('fVer',stats.fw_version);
    const hw=document.getElementById('hWifi');
    if(stats.sta_connected){
      hw.textContent='⬤ '+stats.sta_ssid+' · '+stats.sta_ip;
      hw.style.color='var(--success)';
    }else{
      hw.textContent='⬤ AP · '+stats.ap_ip;
      hw.style.color='var(--accent)';
    }
    if(stats.hub_url&&!document.getElementById('hubUrl').value)
      document.getElementById('hubUrl').value=stats.hub_url;
    updateSteps(stats);
    updateChecklist(stats);
  }catch(e){console.error(e)}
}

function fmtUp(s){
  if(!s&&s!==0)return'—';
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sc=s%60;
  if(h)return h+'h '+m+'m '+sc+'s';
  if(m)return m+'m '+sc+'s';
  return sc+'s';
}

function updateSteps(s){
  const set=(id,done,act)=>{
    const e=document.getElementById(id); if(!e)return;
    e.className='step'+(done?' done':act?' active':'');
    const n=e.querySelector('.step-n');
    if(n)n.textContent=done?'✓':n.textContent;
  };
  set('st1',s.sta_connected,true);
  set('st2',!!(s.hub_url),s.sta_connected);
  set('st3',false,s.sta_connected&&s.hub_url);
  set('st4',false,false);
}

function updateChecklist(s){
  const set=(id,done,act)=>{
    const e=document.getElementById(id); if(!e)return;
    e.className='cn'+(done?' done':act?' act':'');
    if(done)e.textContent='✓';
  };
  set('cn1',s.sta_connected,true);
  set('cn2',false,s.sta_connected);
  set('cn3',!!(s.hub_url),s.sta_connected);
}

// ── WiFi ───────────────────────────────────────────────────────────────────
async function scanWifi(){
  const L=document.getElementById('netList');
  L.innerHTML='<div style="color:var(--muted);font-size:12px;padding:6px">Scanning… (2-3 seconds)</div>';
  try{
    const r=await fetch('/api/wifi/scan'); const d=await r.json();
    console.log('wifi scan', d);
    L.innerHTML='';
    if(!d.networks||!d.networks.length){
      L.innerHTML='<div style="color:var(--muted);font-size:12px;padding:6px">No visible SSIDs found. Raw AP records: '+(d.count_raw??0)+'. Blank results are usually hidden SSIDs or incompatible scan records.</div>';return;
    }
    d.networks.sort((a,b)=>b.rssi-a.rssi);
    for(const n of d.networks){
      const item=document.createElement('div');
      item.className='net-item';
      item.innerHTML=`<span>${n.secure?'🔒 ':''}<strong>${esc(n.ssid)}</strong></span><span class="net-rssi">${bars(n.rssi)} ${n.rssi}dBm</span>`;
      item.onclick=()=>{
        document.querySelectorAll('.net-item').forEach(e=>e.classList.remove('sel'));
        item.classList.add('sel');
        document.getElementById('wSSID').value=n.ssid;
        document.getElementById('wPass').focus();
      };
      L.appendChild(item);
    }
  }catch(e){L.innerHTML='<div style="color:var(--danger);font-size:12px;padding:6px">Scan failed</div>'}
}

function bars(r){return r>-50?'▂▄▆█':r>-65?'▂▄▆·':r>-75?'▂▄··':'▂···'}

async function connectWifi(){
  const ssid=document.getElementById('wSSID').value.trim();
  const pass=document.getElementById('wPass').value;
  const al=document.getElementById('wAlert');
  if(!ssid){showA(al,'err','Enter an SSID');return}
  showA(al,'inf','Connecting to "'+ssid+'"…');
  document.getElementById('btnConn').disabled=true;
  try{
    await fetch('/api/wifi/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid,pass})});
    let tries=0;
    const poll=setInterval(async()=>{
      tries++;
      const r=await fetch('/api/wifi/status'); const s=await r.json();
      if(s.connected){
        clearInterval(poll);
        showA(al,'ok','Connected! STA IP: '+s.ip);
        document.getElementById('btnConn').disabled=false;
        loadStats();
      }else if(tries>20){
        clearInterval(poll);
        showA(al,'err','Timed out — '+(s.status||'not connected')+' ('+(s.status_code??'?')+'). Check serial log for disconnect reason.');
        document.getElementById('btnConn').disabled=false;
      }
    },1500);
  }catch(e){showA(al,'err',e.message);document.getElementById('btnConn').disabled=false}
}

async function disconnectWifi(){
  await fetch('/api/wifi/disconnect',{method:'POST'}).catch(()=>{});
  loadStats();
}

// ── Hub ────────────────────────────────────────────────────────────────────
async function saveHub(){
  const url=document.getElementById('hubUrl').value.trim();
  const al=document.getElementById('hubAlert');
  if(!url){showA(al,'err','Enter a hub URL');return}
  try{
    await fetch('/api/hub/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
    showA(al,'ok','Hub URL saved. Check In to register this device.');
    loadStats();
  }catch(e){showA(al,'err',e.message)}
}

async function testHub(){
  const url=document.getElementById('hubUrl').value.trim();
  const al=document.getElementById('hubAlert');
  if(!url){showA(al,'err','Enter a hub URL first');return}
  showA(al,'inf','Testing…');
  try{
    const r=await fetch('/api/hub/test?url='+encodeURIComponent(url));
    const d=await r.json();
    if(d.ok) showA(al,'ok','Hub reachable — '+d.service);
    else showA(al,'err','Hub not reachable: '+(d.error||'unknown'));
  }catch(e){showA(al,'err','Test failed: '+e.message)}
}

async function checkinHub(){
  const al=document.getElementById('hubAlert');
  showA(al,'inf','Checking in…');
  try{
    const r=await fetch('/api/hub/checkin',{method:'POST'});
    const d=await r.json();
    if(d.ok) showA(al,'ok','Checked in! Find this device in Fleet → Pair to authorize OTA.');
    else showA(al,'err','Checkin failed: '+(d.error||'not connected'));
  }catch(e){showA(al,'err','Checkin failed: '+e.message)}
}

// ── Firmware ───────────────────────────────────────────────────────────────
function setupDrop(){
  const z=document.getElementById('dz');
  z.addEventListener('dragover',e=>{e.preventDefault();z.classList.add('drag')});
  z.addEventListener('dragleave',()=>z.classList.remove('drag'));
  z.addEventListener('drop',e=>{e.preventDefault();z.classList.remove('drag');if(e.dataTransfer.files[0])setFile(e.dataTransfer.files[0])});
}
function onFile(i){if(i.files[0])setFile(i.files[0])}
function setFile(f){
  fwFile=f;
  document.getElementById('dzName').textContent=f.name+' ('+( f.size/1024).toFixed(1)+' KB)';
  document.getElementById('btnFlash').disabled=false;
}

async function flash(){
  if(!fwFile)return;
  if(!confirm('Flash "'+fwFile.name+'" to this device?\n\nThe device will restart after flashing.'))return;
  const al=document.getElementById('fwAlert');
  const prog=document.getElementById('fwProg');
  const bar=document.getElementById('fwBar');
  prog.classList.remove('hidden'); bar.style.width='0%';
  showA(al,'inf','Uploading '+fwFile.name+'…');
  document.getElementById('btnFlash').disabled=true;
  const fd=new FormData(); fd.append('file',fwFile);
  const xhr=new XMLHttpRequest();
  xhr.upload.onprogress=e=>{if(e.lengthComputable)bar.style.width=(e.loaded/e.total*100).toFixed(0)+'%'};
  xhr.onload=()=>{
    if(xhr.status===200){bar.style.width='100%';showA(al,'ok','Flash complete! Device is restarting…')}
    else{showA(al,'err','Flash failed ('+xhr.status+'): '+xhr.responseText);document.getElementById('btnFlash').disabled=false}
  };
  xhr.onerror=()=>{showA(al,'err','Upload error — device may already be rebooting');document.getElementById('btnFlash').disabled=false};
  xhr.open('POST','/api/ota/update'); xhr.send(fd);
}

// ── Reboot ─────────────────────────────────────────────────────────────────
async function reboot(){
  if(!confirm('Reboot device?'))return;
  await fetch('/api/reboot',{method:'POST'}).catch(()=>{});
  setTimeout(()=>location.reload(),4000);
}

// ── Helpers ────────────────────────────────────────────────────────────────
function showA(el,type,msg){el.className='alert '+type;el.textContent=msg;el.classList.remove('hidden')}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
</script>
</body>
</html>
)espai_html";

// ═══════════════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════════════

static void sendJson(int code, const String& body) {
  server.send(code, "application/json", body);
}

static String deriveNodeId() {
  uint8_t mac[6], hash[32];
  WiFi.macAddress(mac);
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0);
  mbedtls_md_starts(&ctx);
  mbedtls_md_update(&ctx, mac, 6);
  mbedtls_md_finish(&ctx, hash);
  mbedtls_md_free(&ctx);
  String id = "node-";
  for (int i = 0; i < 6; i++) {
    if (hash[i] < 0x10) id += "0";
    id += String(hash[i], HEX);
  }
  return id;
}


static const char* wifiStatusName(wl_status_t s) {
  switch (s) {
    case WL_IDLE_STATUS:      return "IDLE";
    case WL_NO_SSID_AVAIL:    return "NO_SSID";
    case WL_SCAN_COMPLETED:   return "SCAN_DONE";
    case WL_CONNECTED:        return "CONNECTED";
    case WL_CONNECT_FAILED:   return "CONNECT_FAILED";
    case WL_CONNECTION_LOST:  return "CONNECTION_LOST";
    case WL_DISCONNECTED:     return "DISCONNECTED";
    default:                  return "UNKNOWN";
  }
}

static void prepWifiRadio() {
  WiFi.mode(WIFI_AP_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);

  // Keep scans on US 2.4 GHz channels. Put OpenWrt test SSID on ch 1/6/11.
  wifi_country_t country = { "US", 1, 11, WIFI_COUNTRY_POLICY_MANUAL };
  esp_wifi_set_country(&country);
}

static void logWifiDiag(const char* tag) {
  Serial.printf("[WiFi] %s mode=%d status=%s(%d) ap_ip=%s sta_ip=%s rssi=%d heap=%u\\n",
                tag,
                (int)WiFi.getMode(),
                wifiStatusName(WiFi.status()),
                (int)WiFi.status(),
                WiFi.softAPIP().toString().c_str(),
                WiFi.localIP().toString().c_str(),
                WiFi.RSSI(),
                ESP.getFreeHeap());
}

// ═══════════════════════════════════════════════════════════════════════════
//  ROUTE HANDLERS
// ═══════════════════════════════════════════════════════════════════════════

void handleRoot() {
  server.send_P(200, "text/html", PAGE_HTML);
}

void handleStats() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char macStr[18];
  snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

  g_staConnected = (WiFi.status() == WL_CONNECTED);

  JsonDocument doc;
  doc["node_id"]       = g_nodeId;
  doc["fw_name"]       = FW_NAME;
  doc["fw_version"]    = FW_VERSION;
  doc["chip_model"]    = ESP.getChipModel();
  doc["chip_cores"]    = ESP.getChipCores();
  doc["chip_freq_mhz"] = ESP.getCpuFreqMHz();
  doc["flash_mb"]      = (int)(ESP.getFlashChipSize() / (1024 * 1024));
  doc["free_heap"]     = (int)ESP.getFreeHeap();
  doc["heap_size"]     = (int)ESP.getHeapSize();
  doc["uptime_s"]      = (int)(millis() / 1000);
  doc["mac"]           = macStr;
  doc["ap_ssid"]       = AP_SSID;
  doc["ap_ip"]         = WiFi.softAPIP().toString();
  doc["sta_connected"] = g_staConnected;
  doc["sta_ssid"]      = g_staSSID;
  doc["sta_ip"]        = g_staConnected ? WiFi.localIP().toString() : "";
  doc["sta_rssi"]      = g_staConnected ? WiFi.RSSI() : 0;
  doc["hub_url"]       = g_hubUrl;
  doc["hostname"]      = WiFi.getHostname();

  String out;
  serializeJson(doc, out);
  sendJson(200, out);
}

void handleWifiScan() {
  prepWifiRadio();
  logWifiDiag("scan-before");
  Serial.println("[WiFi] Starting active scan...");

  // async=false, show_hidden=true, passive=false, max_ms_per_chan=500
  int n = WiFi.scanNetworks(false, true, false, 500);

  JsonDocument doc;
  JsonArray nets = doc["networks"].to<JsonArray>();
  doc["count_raw"] = n;
  doc["status"] = wifiStatusName(WiFi.status());

  if (n <= 0) {
    Serial.printf("[WiFi] Scan found %d networks\n", n);
    WiFi.scanDelete();
    String out;
    serializeJson(doc, out);
    sendJson(200, out);
    return;
  }

  for (int i = 0; i < n && i < 50; i++) {
    String ssid = WiFi.SSID(i);
    int32_t rssi = WiFi.RSSI(i);
    int32_t chan = WiFi.channel(i);
    wifi_auth_mode_t auth = WiFi.encryptionType(i);
    String bssid = WiFi.BSSIDstr(i);

    Serial.printf("[WiFi] %02d ssid='%s' rssi=%d ch=%d auth=%d bssid=%s\n",
                  i,
                  ssid.length() ? ssid.c_str() : "(hidden/blank)",
                  rssi,
                  chan,
                  (int)auth,
                  bssid.c_str());

    // Blank SSIDs are normally hidden SSIDs or incomplete scan records.
    // Keep them out of the clickable UI; manually typed SSIDs still work.
    if (ssid.isEmpty()) continue;

    JsonObject net = nets.add<JsonObject>();
    net["ssid"]    = ssid;
    net["rssi"]    = rssi;
    net["secure"]  = (auth != WIFI_AUTH_OPEN);
    net["channel"] = chan;
    net["auth"]    = (int)auth;
    net["bssid"]   = bssid;
  }

  WiFi.scanDelete();
  logWifiDiag("scan-after");

  String out;
  serializeJson(doc, out);
  sendJson(200, out);
}

void handleWifiConnect() {
  if (!server.hasArg("plain")) { sendJson(400, R"({"error":"no body"})"); return; }
  JsonDocument req;
  if (deserializeJson(req, server.arg("plain")) != DeserializationError::Ok) {
    sendJson(400, R"({"error":"invalid JSON"})"); return;
  }

  String ssid = req["ssid"] | "";
  String pass = req["pass"] | "";
  ssid.trim();

  if (ssid.isEmpty()) { sendJson(400, R"({"error":"ssid required"})"); return; }

  prefs.begin("espai", false);
  prefs.putString("sta_ssid", ssid);
  prefs.putString("sta_pass", pass);
  prefs.end();

  g_staSSID = ssid;
  g_staPass = pass;
  g_staConnected = false;

  prepWifiRadio();
  Serial.printf("[WiFi] Connecting to SSID='%s' pass_len=%d\n", g_staSSID.c_str(), g_staPass.length());
  logWifiDiag("connect-before");

  WiFi.disconnect(false, false);
  delay(250);
  WiFi.begin(g_staSSID.c_str(), g_staPass.c_str());

  sendJson(200, R"({"status":"connecting"})");
}

void handleWifiDisconnect() {
  WiFi.disconnect(false, false);
  g_staConnected = false;
  prepWifiRadio();
  sendJson(200, R"({"status":"disconnected"})");
}

void handleWifiStatus() {
  g_staConnected = (WiFi.status() == WL_CONNECTED);
  JsonDocument doc;
  doc["connected"] = g_staConnected;
  doc["ssid"]      = g_staConnected ? WiFi.SSID() : g_staSSID;
  doc["saved_ssid"] = g_staSSID;
  doc["ip"]        = g_staConnected ? WiFi.localIP().toString() : "";
  doc["rssi"]      = g_staConnected ? WiFi.RSSI() : 0;
  doc["status"]    = wifiStatusName(WiFi.status());
  doc["status_code"] = (int)WiFi.status();
  doc["mode"]      = (int)WiFi.getMode();
  String out;
  serializeJson(doc, out);
  sendJson(200, out);
}

void handleHubSave() {
  if (!server.hasArg("plain")) { sendJson(400, R"({"error":"no body"})"); return; }
  JsonDocument req;
  if (deserializeJson(req, server.arg("plain")) != DeserializationError::Ok) {
    sendJson(400, R"({"error":"invalid JSON"})"); return;
  }
  String url = req["url"] | "";
  prefs.begin("espai", false);
  prefs.putString("hub_url", url);
  prefs.end();
  g_hubUrl = url;
  sendJson(200, R"({"status":"ok"})");
}

void handleHubTest() {
  String url = server.arg("url");
  if (url.isEmpty()) url = g_hubUrl;
  if (url.isEmpty()) { sendJson(400, R"({"ok":false,"error":"no URL"})"); return; }
  if (!g_staConnected) { sendJson(200, R"({"ok":false,"error":"not on home WiFi yet"})"); return; }

  HTTPClient http;
  http.begin(url + "/api/status");
  http.setTimeout(4000);
  int code = http.GET();
  if (code == 200) {
    JsonDocument resp;
    if (deserializeJson(resp, http.getString()) == DeserializationError::Ok) {
      String svc = resp["service"] | "ESPAI Hub";
      String ver = resp["version"] | "?";
      sendJson(200, "{\"ok\":true,\"service\":\"" + svc + " v" + ver + "\"}");
    } else {
      sendJson(200, R"({"ok":true,"service":"ESPAI Hub"})");
    }
  } else {
    sendJson(200, "{\"ok\":false,\"error\":\"HTTP " + String(code) + "\"}");
  }
  http.end();
}

void handleHubCheckin() {
  if (!g_staConnected || g_hubUrl.isEmpty()) {
    sendJson(200, R"({"ok":false,"error":"connect to home WiFi and save hub URL first"})");
    return;
  }

  uint8_t mac[6];
  WiFi.macAddress(mac);
  char macStr[18];
  snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

  JsonDocument body;
  body["id"]         = g_nodeId;
  body["name"]       = WiFi.getHostname();
  body["board"]      = String(ESP.getChipModel());
  body["fw_version"] = FW_VERSION;
  body["ip"]         = WiFi.localIP().toString();
  JsonObject caps    = body["capabilities"].to<JsonObject>();
  caps["ota"]        = true;
  caps["provision"]  = true;

  String bodyStr;
  serializeJson(body, bodyStr);

  HTTPClient http;
  http.begin(g_hubUrl + "/api/devices/checkin");
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);
  int code = http.POST(bodyStr);
  http.end();

  if (code == 200) {
    sendJson(200, R"({"ok":true,"message":"Checked in. Look for this device in Fleet view and click Pair."})");
  } else {
    sendJson(200, "{\"ok\":false,\"error\":\"Hub returned HTTP " + String(code) + "\"}");
  }
}

void handleReboot() {
  sendJson(200, R"({"status":"rebooting"})");
  delay(200);
  ESP.restart();
}

// OTA — two-handler pattern required by WebServer
void handleOTAComplete() {
  if (g_otaError) {
    sendJson(500, R"({"status":"failed","error":"OTA write error — see serial"})");
  } else {
    sendJson(200, R"({"status":"ok"})");
    delay(500);
    ESP.restart();
  }
}

void handleOTAUpload() {
  HTTPUpload& upload = server.upload();
  if (upload.status == UPLOAD_FILE_START) {
    g_otaError = false;
    Serial.printf("[OTA] Start: %s\n", upload.filename.c_str());
    if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
      Update.printError(Serial);
      g_otaError = true;
    }
  } else if (upload.status == UPLOAD_FILE_WRITE) {
    if (!g_otaError && Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
      Update.printError(Serial);
      g_otaError = true;
    }
  } else if (upload.status == UPLOAD_FILE_END) {
    if (!g_otaError && !Update.end(true)) {
      Update.printError(Serial);
      g_otaError = true;
    }
    Serial.printf("[OTA] Done: %u bytes. Error: %s\n", upload.totalSize, g_otaError ? "yes" : "no");
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SETUP
// ═══════════════════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println();
  Serial.println("╔════════════════════════════════╗");
  Serial.println("║   ESPAI Provisioning Firmware  ║");
  Serial.printf( "║   v%-28s║\n", FW_VERSION);
  Serial.println("╚════════════════════════════════╝");

  // Load saved credentials
  prefs.begin("espai", true);
  g_staSSID = prefs.getString("sta_ssid", "");
  g_staPass = prefs.getString("sta_pass", "");
  g_hubUrl  = prefs.getString("hub_url",  "");
  prefs.end();

  // Must initialize WiFi before macAddress/node-id generation.
  prepWifiRadio();
  g_nodeId = deriveNodeId();

  Serial.printf("Node ID:  %s\n", g_nodeId.c_str());
  Serial.printf("Chip:     %s × %d cores @ %d MHz\n",
                ESP.getChipModel(), ESP.getChipCores(), ESP.getCpuFreqMHz());
  Serial.printf("Flash:    %u MB\n", ESP.getFlashChipSize() / (1024 * 1024));
  Serial.printf("Heap:     %u bytes free\n", ESP.getFreeHeap());

  // Start AP
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.printf("AP:       SSID=%s  IP=%s\n", AP_SSID, WiFi.softAPIP().toString().c_str());
  Serial.printf("          Pass=%s\n", AP_PASS);

  // Connect to STA if credentials saved
  if (!g_staSSID.isEmpty()) {
    Serial.printf("STA:      Connecting to \"%s\"…\n", g_staSSID.c_str());
    WiFi.begin(g_staSSID.c_str(), g_staPass.c_str());
  }

  // mDNS hostname: espai-<first 6 chars of node id hex>
  String hostname = "espai-" + g_nodeId.substring(5, 11);
  WiFi.setHostname(hostname.c_str());
  if (MDNS.begin(hostname.c_str())) {
    MDNS.addService("_espai-provision", "_tcp", 80);
    MDNS.addService("_http", "_tcp", 80);
    Serial.printf("mDNS:     %s.local\n", hostname.c_str());
  }

  // Routes
  server.on("/",                    HTTP_GET,  handleRoot);
  server.on("/api/stats",           HTTP_GET,  handleStats);
  server.on("/api/wifi/scan",       HTTP_GET,  handleWifiScan);
  server.on("/api/wifi/connect",    HTTP_POST, handleWifiConnect);
  server.on("/api/wifi/disconnect", HTTP_POST, handleWifiDisconnect);
  server.on("/api/wifi/status",     HTTP_GET,  handleWifiStatus);
  server.on("/api/hub/save",        HTTP_POST, handleHubSave);
  server.on("/api/hub/test",        HTTP_GET,  handleHubTest);
  server.on("/api/hub/checkin",     HTTP_POST, handleHubCheckin);
  server.on("/api/reboot",          HTTP_POST, handleReboot);
  server.on("/api/ota/update",      HTTP_POST, handleOTAComplete, handleOTAUpload);

  // Captive portal redirect for any unknown path
  server.onNotFound([]() {
    server.sendHeader("Location", "http://192.168.4.1/");
    server.send(302);
  });

  server.begin();
  Serial.println();
  Serial.println("Portal:   http://192.168.4.1  (connect to ESPAI-Setup first)");
  if (!g_hubUrl.isEmpty()) Serial.printf("Hub:      %s\n", g_hubUrl.c_str());
  Serial.println("═══════════ READY ════════════════");
}

// ═══════════════════════════════════════════════════════════════════════════
//  LOOP
// ═══════════════════════════════════════════════════════════════════════════

void loop() {
  server.handleClient();

  // Track STA connection state changes
  bool nowConnected = (WiFi.status() == WL_CONNECTED);
  if (nowConnected != g_staConnected) {
    g_staConnected = nowConnected;
    if (g_staConnected) {
      Serial.printf("[WiFi] STA connected — IP: %s  RSSI: %d dBm\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
      Serial.println("[WiFi] STA disconnected");
    }
  }

  delay(1);
}
