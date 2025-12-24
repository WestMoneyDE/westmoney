const express = require("express");
const axios = require("axios");
require("dotenv").config();

const app = express();
app.use(express.json());

const config = {
    accessToken: process.env.WHATSAPP_ACCESS_TOKEN,
    phoneNumberId: process.env.WHATSAPP_PHONE_NUMBER_ID,
    verifyToken: process.env.WHATSAPP_WEBHOOK_VERIFY_TOKEN || "westmoney_webhook_2025"
};

const whatsappAPI = axios.create({
    baseURL: "https://graph.facebook.com/v21.0",
    headers: {
        "Authorization": "Bearer " + config.accessToken,
        "Content-Type": "application/json"
    }
});

async function sendMessage(to, text) {
    var response = await whatsappAPI.post("/" + config.phoneNumberId + "/messages", {
        messaging_product: "whatsapp",
        to: to,
        type: "text",
        text: { body: text }
    });
    console.log("Sent to " + to);
    return response.data;
}

app.get("/webhook", function(req, res) {
    var mode = req.query["hub.mode"];
    var token = req.query["hub.verify_token"];
    var challenge = req.query["hub.challenge"];
    if (mode === "subscribe" && token === config.verifyToken) {
        console.log("Webhook verified");
        res.status(200).send(challenge);
    } else {
        res.sendStatus(403);
    }
});

app.post("/webhook", async function(req, res) {
    try {
        var body = req.body;
        if (body.object === "whatsapp_business_account") {
            var entries = body.entry || [];
            for (var i = 0; i < entries.length; i++) {
                var changes = entries[i].changes || [];
                for (var j = 0; j < changes.length; j++) {
                    if (changes[j].field === "messages") {
                        var msgs = changes[j].value.messages || [];
                        for (var k = 0; k < msgs.length; k++) {
                            await handleMessage(msgs[k]);
                        }
                    }
                }
            }
        }
        res.sendStatus(200);
    } catch (err) {
        console.error("Error:", err);
        res.sendStatus(500);
    }
});

async function handleMessage(msg) {
    var from = msg.from;
    var input = "";
    
    if (msg.type === "text") {
        input = msg.text.body.toLowerCase();
    } else if (msg.type === "interactive") {
        if (msg.interactive.button_reply) input = msg.interactive.button_reply.id;
        if (msg.interactive.list_reply) input = msg.interactive.list_reply.id;
    }
    
    console.log("From " + from + ": " + input);
    
    if (input === "hi" || input === "hallo" || input === "menu") {
        await sendMessage(from, "Willkommen bei West Money!\n\nServices:\n1. Smart Home\n2. Bauservice\n3. Angebot\n4. Kontakt\n\nAntworten Sie mit der Nummer.");
    } else if (input === "1" || input === "smart_home") {
        await sendMessage(from, "Smart Home - LOXONE Partner\n\nBis 50% Energieersparnis!\n\nFuer Angebot antworten Sie: Angebot");
    } else if (input === "2" || input === "bau") {
        await sendMessage(from, "West Money Bau\n\nBarrierefreies Bauen\nEnergetische Sanierung\n\nFuer Beratung: Angebot");
    } else if (input === "3" || input === "angebot") {
        await sendMessage(from, "Angebot anfordern\n\nSenden Sie:\n- Name\n- Projekt\n- Email\n\nWir melden uns in 24h!");
    } else if (input === "4" || input === "kontakt") {
        await sendMessage(from, "Kontakt\n\nTel: +49 177 454 7727\nEmail: info@west-money.com\nWeb: west-money.com");
    } else {
        await sendMessage(from, "West Money Bot\n\nAntworten Sie mit Menu");
    }
}

app.get("/health", function(req, res) {
    res.json({ status: "ok", app: "West Money WhatsApp Bot" });
});

var PORT = process.env.PORT || 3001;
app.listen(PORT, function() {
    console.log("=================================");
    console.log("  WEST MONEY WhatsApp Bot");
    console.log("  Port: " + PORT);
    console.log("  Phone ID: " + config.phoneNumberId);
    console.log("=================================");
});
