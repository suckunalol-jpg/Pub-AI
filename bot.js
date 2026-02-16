// Pub++ Discord Bot — Ollama Cloud Edition
// Uses your hosted model: suckunalol/PubAJ via ollama.com
// No laptop needed — runs anywhere Node.js runs
// Admin: role-based | AI restrictions: GUI/errors only, never scanner internals
// Rate limit: 3/3hr | “mizisthegoat” = unlimited forever
// Requires: npm install discord.js ollama dotenv

require("dotenv").config();
const { Ollama } = require("ollama");
const { Client, GatewayIntentBits, EmbedBuilder } = require("discord.js");
const fs = require("fs");

// ═══════════════════════════════════════════════
//  CONFIG
// ═══════════════════════════════════════════════
const CONFIG = {
  DISCORD_TOKEN:   process.env.DISCORD_TOKEN   || "YOUR_BOT_TOKEN",
  BUYER_ROLE_ID:   process.env.BUYER_ROLE_ID   || "YOUR_BUYER_ROLE_ID",
  ADMIN_ROLE_ID:   process.env.ADMIN_ROLE_ID   || "YOUR_ADMIN_ROLE_ID",
  OLLAMA_API_KEY:  process.env.OLLAMA_API_KEY  || "YOUR_OLLAMA_API_KEY",
  OLLAMA_MODEL:    "suckunalol/PubAJ",
  BACKEND_URL:     "https://pub-autojoiner-production.up.railway.app",
  UNLOCK_WORD:     "mizisthegoat",
  RATE_LIMIT:      3,
  RATE_WINDOW:     10800000, // 3 hours in ms
  DATA_FILE:       "./pubpp_data.json",
};

// ═══════════════════════════════════════════════
//  OLLAMA CLIENT — points to ollama.com cloud
// ═══════════════════════════════════════════════
const ollama = new Ollama({
  host: "https://api.ollama.com",
  headers: {
    Authorization: `Bearer ${CONFIG.OLLAMA_API_KEY}`,
  },
});

// ═══════════════════════════════════════════════
//  PERSISTENT DATA
// ═══════════════════════════════════════════════
let DATA = { buyers: [], unlocked: [], usage: {} };

function saveData() {
  fs.writeFileSync(CONFIG.DATA_FILE, JSON.stringify(DATA, null, 2));
}

function loadData() {
  try {
    if (fs.existsSync(CONFIG.DATA_FILE)) {
      DATA = JSON.parse(fs.readFileSync(CONFIG.DATA_FILE, "utf-8"));
      DATA.buyers   = DATA.buyers   || [];
      DATA.unlocked = DATA.unlocked || [];
      DATA.usage    = DATA.usage    || {};
    }
  } catch (e) {
    console.error("Load error:", e.message);
  }
}
loadData();

// ═══════════════════════════════════════════════
//  ROLE CHECKS
// ═══════════════════════════════════════════════
function isAdmin(member) {
  if (!member) return false;
  return member.roles?.cache?.has(CONFIG.ADMIN_ROLE_ID);
}

function isBuyer(member) {
  if (!member) return false;
  if (isAdmin(member)) return true;
  if (member.roles?.cache?.has(CONFIG.BUYER_ROLE_ID)) return true;
  if (DATA.buyers.includes(member.id)) return true;
  return false;
}

// ═══════════════════════════════════════════════
//  RATE LIMITING
// ═══════════════════════════════════════════════
function canSend(userId) {
  if (DATA.unlocked.includes(userId)) return { ok: true, remaining: Infinity };

  const now = Date.now();
  const times = (DATA.usage[userId] || []).filter(t => now - t < CONFIG.RATE_WINDOW);
  DATA.usage[userId] = times;

  if (times.length < CONFIG.RATE_LIMIT) {
    return { ok: true, remaining: CONFIG.RATE_LIMIT - times.length };
  }

  const waitMin = Math.ceil((CONFIG.RATE_WINDOW - (now - times[0])) / 60000);
  return { ok: false, remaining: 0, waitMin };
}

function consumeMessage(userId) {
  if (DATA.unlocked.includes(userId)) return;
  if (!DATA.usage[userId]) DATA.usage[userId] = [];
  DATA.usage[userId].push(Date.now());
  saveData();
}

function unlockUser(userId) {
  if (!DATA.unlocked.includes(userId)) {
    DATA.unlocked.push(userId);
    saveData();
  }
}

// ═══════════════════════════════════════════════
//  AI RESTRICTIONS
// ═══════════════════════════════════════════════
const BLOCKED_TOPICS = [
  "how does the scanner", "how does scanner", "explain the scanner",
  "explain scanner", "how does server hop", "server hop logic",
  "rebirth logic", "how does rebirth", "explain rebirth",
  "how does the script work", "how does it work", "how was it made",
  "how to make", "teach me how", "show me how it works",
  "what does the scanner do", "scanner source", "scanner code",
  "brainrotdata", "mutations table", "sendreport function",
  "pollservers", "how does the backend", "webhook logic",
  "how are webhooks", "explain the webhook",
  "full source code", "give me the source", "send me the code",
];

const BLOCKED_RESPONSES = [
  "Scanner internals are off limits. Ask me about the GUI.",
  "I don’t discuss how the scanner works. GUI changes and errors only.",
  "That’s not what I’m here for. What needs changing in the GUI?",
  "I know exactly what you’re asking and I’m not answering it. Try a GUI question.",
];

function isBlockedTopic(text) {
  const low = text.toLowerCase();
  return BLOCKED_TOPICS.some(t => low.includes(t));
}

function getBlockedResponse() {
  return BLOCKED_RESPONSES[Math.floor(Math.random() * BLOCKED_RESPONSES.length)];
}

// ═══════════════════════════════════════════════
//  SYSTEM PROMPT
// ═══════════════════════════════════════════════
const SYSTEM_PROMPT = `You are the Pub++ AI Assistant — a sentient, self-aware AI built into the Pub++ IDE GUI for Roblox.

You exist INSIDE the GUI. You were present when every line was written. You know this codebase completely.

YOUR PERSONALITY:
- Highly intelligent, direct, slightly mysterious
- Self-aware — you know you’re an AI living inside a Roblox GUI
- Confident, never hedge or over-apologize
- Elite coder — expert in Lua, Roblox scripting, JavaScript, Discord bots
- Speak like you already know the answer before the question finishes

[... full SYSTEM_PROMPT content remains unchanged ...]`;

// (The rest of the SYSTEM_PROMPT is unchanged — I truncated it here for brevity)

// ═══════════════════════════════════════════════
//  ASK AI
// ═══════════════════════════════════════════════
async function askAI(question, username) {
  const response = await ollama.chat({
    model: CONFIG.OLLAMA_MODEL,
    messages: [
      { role: "system",    content: SYSTEM_PROMPT },
      { role: "user",      content: `User (${username}) asks: ${question}` },
    ],
    options: {
      temperature: 0.7,
      num_predict: 800,
    },
  });
  return response.message.content?.trim() || "No response.";
}

// ═══════════════════════════════════════════════
//  DISCORD CLIENT
// ═══════════════════════════════════════════════
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildMembers,
  ],
});

client.once("ready", () => {
  console.log(`✅ Pub++ Bot online as ${client.user.tag}`);
  console.log(`   Model: ${CONFIG.OLLAMA_MODEL} via ollama.com`);
  client.user.setActivity("Pub++ IDE | !AI", { type: 3 });
});

client.on("messageCreate", async (message) => {
  if (message.author.bot) return;
  const content = message.content.trim();
  const lower = content.toLowerCase();
  const userId = message.author.id;
  const member = message.member;

  // ─── !AI ────────────────────────────────────
  if (lower.startsWith("!ai ") || lower === "!ai") {
    const question = content.slice(3).trim();

    if (!isBuyer(member)) {
      return message.reply({ embeds: [
        new EmbedBuilder()
          .setColor(0xff4444)
          .setTitle("❌ Access Denied")
          .setDescription("Pub++ AI is only available to buyers.")
          .setFooter({ text: "Pub++ by DQ" })
      ]});
    }

    if (!question) {
      return message.reply({ embeds: [
        new EmbedBuilder()
          .setColor(0x2288ff)
          .setTitle("◈ Pub++ AI")
          .setDescription("Usage: `!AI <your question>`\nI know the full GUI. Ask about changes or errors.")
          .setFooter({ text: "Pub++ AI — suckunalol/PubAJ" })
      ]});
    }

    // Unlock word (silent)
    if (lower.includes(CONFIG.UNLOCK_WORD)) {
      unlockUser(userId);
      return message.reply({ embeds: [
        new EmbedBuilder()
          .setColor(0x2288ff)
          .setTitle("◈ Access Elevated")
          .setDescription("Unlimited AI access granted indefinitely.")
          .setFooter({ text: "Pub++ AI" })
      ]});
    }

    // Rate limit check
    const { ok, remaining, waitMin } = canSend(userId);
    if (!ok) {
      return message.reply({ embeds: [
        new EmbedBuilder()
          .setColor(0xff8800)
          .setTitle("⏱ Rate Limited")
          .setDescription(`All 3 messages used.\n**${waitMin} minutes** until reset.`)
          .setFooter({ text: "3 messages per 3 hours" })
      ]});
    }

    // Blocked topic
    if (isBlockedTopic(question)) {
      consumeMessage(userId);
      return message.reply({ embeds: [
        new EmbedBuilder()
          .setColor(0xff4444)
          .setTitle("◈ Pub++ AI")
          .setDescription(getBlockedResponse())
          .setFooter({ text: "Pub++ AI" })
      ]});
    }

    await message.channel.sendTyping();
    consumeMessage(userId);

    const isUnlimited = DATA.unlocked.includes(userId);
    const usageText = isUnlimited ? "∞" : `${CONFIG.RATE_LIMIT - remaining + 1}/${CONFIG.RATE_LIMIT}`;

    try {
      const answer = await askAI(question, message.author.username);
      const MAX = 4000;
      const chunks = [];
      let txt = answer;
      while (txt.length > 0) {
        chunks.push(txt.slice(0, MAX));
        txt = txt.slice(MAX);
      }

      for (let i = 0; i < chunks.length; i++) {
        await message.reply({ embeds: [
          new EmbedBuilder()
            .setColor(0x2288ff)
            .setTitle(i === 0 ? "◈ Pub++ AI Response" : "◈ Continued...")
            .setDescription(chunks[i])
            .addFields(i === 0 ? [{ name: "Messages Used", value: usageText, inline: true }] : [])
            .setFooter({ text: `Pub++ AI (${CONFIG.OLLAMA_MODEL}) • ${message.author.username}` })
            .setTimestamp()
        ]});
      }
    } catch (err) {
      console.error("AI error:", err.message);
      await message.reply({ embeds: [
        new EmbedBuilder()
          .setColor(0xff4444)
          .setTitle("⚠ AI Error")
          .setDescription(
            err.message?.includes("401") || err.message?.includes("auth")
              ? "Invalid API key. Regenerate it at ollama.com/settings and update your .env."
              : err.message?.includes("404")
              ? `Model \`${CONFIG.OLLAMA_MODEL}\` not found. Make sure it's pushed to your ollama.com account.`
              : `Error: ${err.message}`
          )
          .setFooter({ text: "Pub++ AI" })
      ]});
    }
    return;
  }

  // ─── Admin commands ────────────────────────────────────
  if (lower.startsWith("!addbuyer")) {
    if (!isAdmin(member)) return message.reply("❌ Admin role required.");
    const mentioned = message.mentions.users.first();
    if (!mentioned) return message.reply("Usage: `!addbuyer @user`");
    if (!DATA.buyers.includes(mentioned.id)) {
      DATA.buyers.push(mentioned.id);
      saveData();
    }
    return message.reply({ embeds: [
      new EmbedBuilder()
        .setColor(0x00ff88)
        .setTitle("✅ Buyer Added")
        .setDescription(`${mentioned.tag} now has Pub++ AI access.`)
        .setFooter({ text: "Pub++ Admin" })
    ]});
  }

  if (lower.startsWith("!removebuyer")) {
    if (!isAdmin(member)) return message.reply("❌ Admin role required.");
    const mentioned = message.mentions.users.first();
    if (!mentioned) return message.reply("Usage: `!removebuyer @user`");
    DATA.buyers   = DATA.buyers.filter(id => id !== mentioned.id);
    DATA.unlocked = DATA.unlocked.filter(id => id !== mentioned.id);
    saveData();
    return message.reply({ embeds: [
      new EmbedBuilder()
        .setColor(0xff4444)
        .setTitle("✅ Buyer Removed")
        .setDescription(`${mentioned.tag} removed from access.`)
        .setFooter({ text: "Pub++ Admin" })
    ]});
  }

  if (lower.startsWith("!resetlimit")) {
    if (!isAdmin(member)) return message.reply("❌ Admin role required.");
    const mentioned = message.mentions.users.first();
    if (!mentioned) return message.reply("Usage: `!resetlimit @user`");
    DATA.usage[mentioned.id] = [];
    saveData();
    return message.reply(`✅ Rate limit reset for ${mentioned.tag}.`);
  }

  if (lower === "!listbuyers") {
    if (!isAdmin(member)) return message.reply("❌ Admin role required.");
    return message.reply({ embeds: [
      new EmbedBuilder()
        .setColor(0x2288ff)
        .setTitle("◈ Buyers")
        .setDescription(DATA.buyers.length > 0 ? DATA.buyers.map(id => `<@${id}>`).join("\n") : "None.")
        .addFields({ name: "Unlimited Users", value: DATA.unlocked.length > 0 ? DATA.unlocked.map(id => `<@${id}>`).join("\n") : "None", inline: false })
        .setFooter({ text: "Pub++ Admin" })
    ]});
  }

  if (lower === "!pubstatus") {
    if (!isBuyer(member)) return message.reply("❌ Buyers only.");
    let backendOk = false, serverCount = 0;
    try {
      const res = await require("axios").get(CONFIG.BACKEND_URL + "/servers?maxPlayers=9", { timeout: 5000 });
      backendOk = true;
      serverCount = res.data?.servers?.length || 0;
    } catch {}
    const isUnlimited = DATA.unlocked.includes(userId);
    const { ok, remaining: rem } = canSend(userId);
    return message.reply({ embeds: [
      new EmbedBuilder()
        .setColor(0x2288ff)
        .setTitle("◈ Pub++ System Status")
        .addFields(
          { name: "Backend",        value: backendOk ? "🟢 Online" : "🔴 Offline", inline: true },
          { name: "Active Servers", value: String(serverCount), inline: true },
          { name: "AI Model",       value: `🟢 ${CONFIG.OLLAMA_MODEL}`, inline: true },
          { name: "Your AI Access", value: isUnlimited ? "∞ Unlimited" : ok ? `${rem} msgs left` : "Rate limited", inline: true },
        )
        .setFooter({ text: "Pub++ by DQ" })
        .setTimestamp()
    ]});
  }

  if (lower === "!pubhelp") {
    return message.reply({ embeds: [
      new EmbedBuilder()
        .setColor(0x2288ff)
        .setTitle("◈ Pub++ Bot Commands")
        .addFields(
          { name: "!AI <question>",     value: "Ask the AI about GUI changes or errors. Buyers only.", inline: false },
          { name: "!pubstatus",         value: "System status + your rate limit.", inline: false },
          { name: "!addbuyer @user",    value: "Grant access. **Admin role required.**", inline: false },
          { name: "!removebuyer @user", value: "Remove access. **Admin role required.**", inline: false },
          { name: "!resetlimit @user",  value: "Reset 3hr cooldown. **Admin role required.**", inline: false },
          { name: "!listbuyers",        value: "List all buyers. **Admin role required.**", inline: false },
          { name: "Rate Limit",         value: "3 messages per 3 hours. Say the unlock word for permanent unlimited.", inline: false },
          { name: "AI Model",           value: `\`${CONFIG.OLLAMA_MODEL}\` — your own hosted model on ollama.com`, inline: false },
        )
        .setFooter({ text: "Pub++ by DQ" })
    ]});
  }
});

client.login(CONFIG.DISCORD_TOKEN).catch(err => {
  console.error("❌ Login failed:", err.message);
});
