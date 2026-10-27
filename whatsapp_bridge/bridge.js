/**
 * WhatsApp Web Multi-Device Session Bridge for Tracky AI
 * 
 * Uses @whiskeysockets/baileys to connect directly to WhatsApp Web multi-device.
 * - Displays QR code in terminal for linking (or generates Pairing Code)
 * - Persists session in ./auth_info
 * - Forwards incoming messages to Tracky AI FastAPI webhook (http://127.0.0.1:8002/webhook/whatsapp/web)
 * - Exposes HTTP API on port 3001 for outbound proactive reminder messages (/send)
 */

const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const qrcodeTerminal = require('qrcode-terminal');
const path = require('path');
const fs = require('fs');

const PORT = process.env.WHATSAPP_PORT || 3001;
const TRACKY_WEBHOOK_URL = process.env.TRACKY_WEBHOOK_URL || 'http://127.0.0.1:8002/webhook/whatsapp/web';
const AUTH_DIR = path.join(__dirname, 'auth_info');

let sock = null;
let currentQR = null;
let connectionStatus = 'initializing';
let pairingCode = null;

// Ensure auth directory exists
if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
}

// -------------------------------------------------------------
// WhatsApp Multi-Device Connection Logic
// -------------------------------------------------------------
async function connectToWhatsApp() {
    connectionStatus = 'connecting';
    console.log('\n[WhatsApp Bridge] Initializing WhatsApp Web Multi-Device connection...');

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`[WhatsApp Bridge] Using WA Web v${version.join('.')}, isLatest: ${isLatest}`);

    sock = makeWASocket({
        version,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false, // Handled manually with qrcode-terminal
        auth: state,
        browser: ['Tracky AI', 'Desktop', '1.0.0'],
        syncFullHistory: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            currentQR = qr;
            connectionStatus = 'qr_ready';
            console.log('\n============================================================');
            console.log('📱 SCAN THIS QR CODE IN WHATSAPP TO LINK TRACKY AI:');
            console.log('   (WhatsApp -> Linked Devices -> Link a Device)');
            console.log('============================================================\n');
            qrcodeTerminal.generate(qr, { small: true });
            console.log('\nTip: Open http://127.0.0.1:' + PORT + '/qr in your browser if terminal QR is distorted.\n');
        }

        if (connection === 'close') {
            currentQR = null;
            const statusCode = (lastDisconnect?.error)?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            connectionStatus = shouldReconnect ? 'reconnecting' : 'logged_out';

            console.log(`[WhatsApp Bridge] Connection closed. Reason code: ${statusCode}. Reconnecting: ${shouldReconnect}`);

            if (statusCode === DisconnectReason.loggedOut) {
                console.log('[WhatsApp Bridge] Session logged out. Cleaning credentials directory for fresh scan...');
                try {
                    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
                    fs.mkdirSync(AUTH_DIR, { recursive: true });
                } catch (e) {
                    console.error('[WhatsApp Bridge] Error clearing auth dir:', e);
                }
                setTimeout(connectToWhatsApp, 3000);
            } else if (shouldReconnect) {
                setTimeout(connectToWhatsApp, 3000);
            }
        } else if (connection === 'open') {
            currentQR = null;
            connectionStatus = 'connected';
            const userPhone = sock.user?.id ? sock.user.id.split(':')[0] : 'Unknown';
            console.log('\n============================================================');
            console.log(`🟢 WHATSAPP WEB SESSION CONNECTED!`);
            console.log(`   Logged in as: +${userPhone} (${sock.user?.name || 'Tracky Assistant'})`);
            console.log(`   Tracky AI is now actively listening for WhatsApp messages!`);
            console.log('============================================================\n');
        }
    });

    // -------------------------------------------------------------
    // Incoming Message Handler
    // -------------------------------------------------------------
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        for (const msg of messages) {
            // Ignore messages sent by the bot itself
            if (msg.key.fromMe) continue;
            if (!msg.message) continue;

            const remoteJid = msg.key.remoteJid;
            // Ignore status broadcasts
            if (remoteJid === 'status@broadcast') continue;

            // Extract text message content
            const text = (
                msg.message.conversation ||
                msg.message.extendedTextMessage?.text ||
                msg.message.imageMessage?.caption ||
                msg.message.videoMessage?.caption ||
                ''
            ).trim();

            if (!text) continue;

            const senderPhone = remoteJid.replace('@s.whatsapp.net', '').replace('@c.us', '');
            const pushName = msg.pushName || 'Friend';

            console.log(`[WhatsApp Bridge] 📩 Message from ${pushName} (+${senderPhone}): "${text}"`);

            // Forward to Tracky AI FastAPI webhook
            try {
                const response = await fetch(TRACKY_WEBHOOK_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sender: remoteJid,
                        phone: senderPhone,
                        name: pushName,
                        text: text,
                        message_id: msg.key.id,
                        timestamp: msg.messageTimestamp,
                    }),
                });

                if (response.ok) {
                    const data = await response.json();
                    if (data && data.reply) {
                        console.log(`[WhatsApp Bridge] 📤 Sending reply to +${senderPhone}...`);
                        await sock.sendMessage(remoteJid, { text: data.reply });
                    }
                } else {
                    console.error(`[WhatsApp Bridge] Webhook error ${response.status}: ${await response.text()}`);
                }
            } catch (err) {
                console.error('[WhatsApp Bridge] Failed to forward to Tracky webhook:', err.message);
            }
        }
    });
}

// -------------------------------------------------------------
// Express Outbound & Status API
// -------------------------------------------------------------
const app = express();
app.use(express.json());

// Send message endpoint (Called by Tracky scheduler for reminders & proactive alerts)
app.post('/send', async (req, res) => {
    const { to, message } = req.body;
    if (!to || !message) {
        return res.status(400).json({ error: "Missing 'to' or 'message' parameters" });
    }

    if (!sock || connectionStatus !== 'connected') {
        return res.status(503).json({ error: 'WhatsApp Web is not connected', status: connectionStatus });
    }

    // Format recipient JID
    let targetJid = to.trim();
    if (!targetJid.includes('@')) {
        const cleanNumber = targetJid.replace(/[^0-9]/g, '');
        targetJid = `${cleanNumber}@s.whatsapp.net`;
    }

    try {
        console.log(`[WhatsApp Bridge] 🔔 Dispatching message to ${targetJid}: "${message.substring(0, 60)}..."`);
        await sock.sendMessage(targetJid, { text: message });
        return res.json({ success: true, target: targetJid });
    } catch (err) {
        console.error(`[WhatsApp Bridge] Failed to send message to ${targetJid}:`, err);
        return res.status(500).json({ error: err.message });
    }
});

// Status endpoint
app.get('/status', (req, res) => {
    res.json({
        status: connectionStatus,
        user: sock?.user || null,
        qr_available: currentQR !== null,
    });
});

// Browser QR code viewer
app.get('/qr', (req, res) => {
    if (connectionStatus === 'connected') {
        return res.send(`
            <html>
                <body style="font-family:sans-serif; text-align:center; padding:50px; background:#f0f2f5;">
                    <div style="background:white; display:inline-block; padding:30px; border-radius:12px; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
                        <h2 style="color:#25d366;">✅ WhatsApp Connected!</h2>
                        <p>Logged in as: <strong>+${sock.user?.id ? sock.user.id.split(':')[0] : 'WhatsApp User'}</strong></p>
                        <p>Tracky AI is active and responding.</p>
                    </div>
                </body>
            </html>
        `);
    }

    if (!currentQR) {
        return res.send(`
            <html>
                <body style="font-family:sans-serif; text-align:center; padding:50px; background:#f0f2f5;">
                    <h2>Connecting to WhatsApp...</h2>
                    <p>Status: <strong>${connectionStatus}</strong></p>
                    <p>Please wait a moment and refresh this page.</p>
                    <script>setTimeout(() => location.reload(), 2500);</script>
                </body>
            </html>
        `);
    }

    res.send(`
        <html>
            <head>
                <title>Tracky AI - WhatsApp Web Pair</title>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
            </head>
            <body style="font-family:sans-serif; text-align:center; padding:40px; background:#0b141a; color:white;">
                <div style="background:#111b21; display:inline-block; padding:36px; border-radius:16px; border:1px solid #222d34;">
                    <h1 style="color:#25d366; margin-top:0;">📱 Link Tracky AI to WhatsApp</h1>
                    <p style="color:#8696a0; font-size:16px;">1. Open WhatsApp on your phone<br>2. Go to <strong>Settings</strong> > <strong>Linked Devices</strong><br>3. Tap <strong>Link a Device</strong> and point your camera at this code:</p>
                    <div id="qrcode" style="display:flex; justify-content:center; padding:20px; background:white; border-radius:10px; width:260px; height:260px; margin:20px auto;"></div>
                    <p style="color:#8696a0; font-size:13px;">Auto-refreshing when connected...</p>
                </div>
                <script>
                    new QRCode(document.getElementById("qrcode"), {
                        text: "${currentQR}",
                        width: 260,
                        height: 260
                    });
                    setInterval(async () => {
                        const res = await fetch('/status');
                        const data = await res.json();
                        if (data.status === 'connected') location.reload();
                    }, 2000);
                </script>
            </body>
        </html>
    `);
});

// Phone pairing code endpoint (alternative to QR)
app.post('/pair', async (req, res) => {
    const { phoneNumber } = req.body;
    if (!phoneNumber) {
        return res.status(400).json({ error: "Missing 'phoneNumber' parameter" });
    }
    if (!sock) {
        return res.status(503).json({ error: 'WhatsApp socket not initialized' });
    }

    try {
        const cleanNumber = phoneNumber.replace(/[^0-9]/g, '');
        const code = await sock.requestPairingCode(cleanNumber);
        console.log(`[WhatsApp Bridge] 🔑 Pairing code generated for +${cleanNumber}: ${code}`);
        return res.json({ pairingCode: code });
    } catch (err) {
        console.error('[WhatsApp Bridge] Failed to generate pairing code:', err);
        return res.status(500).json({ error: err.message });
    }
});

// Start Express server
app.listen(PORT, '0.0.0.0', () => {
    console.log(`[WhatsApp Bridge] HTTP bridge server running at http://0.0.0.0:${PORT}`);
    connectToWhatsApp();
});
