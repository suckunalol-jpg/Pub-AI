--[[
    Pub AI — Roblox Client
    In-game GUI with AI chat, script scanning, self-modification, and command execution.

    SETUP:
    1. Place this as a LocalScript inside StarterPlayerScripts (or StarterGui)
    2. Place modules/api.lua and modules/scanner.lua as ModuleScripts alongside this script
    3. Set CONFIG.API_KEY and CONFIG.BASE_URL below
    4. Enable HttpService in game settings
]]

-- ============================================================================
-- CONFIG
-- ============================================================================

local CONFIG = {
    API_KEY   = "YOUR_API_KEY_HERE",   -- Get from Pub AI web panel
    BASE_URL  = "http://localhost:8000", -- Your Pub AI backend URL
    WIN_W     = 700,
    WIN_H     = 500,
    FONT      = Enum.Font.GothamMedium,
    FONT_BOLD = Enum.Font.GothamBold,
    FONT_MONO = Enum.Font.RobotoMono,
    MAX_HISTORY = 20,
    HEALTH_INTERVAL = 30, -- seconds between health checks
}

-- ============================================================================
-- COLORS
-- ============================================================================

local C = {
    BG        = Color3.fromRGB(10, 14, 26),
    PANEL     = Color3.fromRGB(16, 20, 36),
    INPUT_BG  = Color3.fromRGB(24, 28, 48),
    ACCENT    = Color3.fromRGB(0, 170, 255),
    ACCENT2   = Color3.fromRGB(130, 80, 255),
    TEXT      = Color3.fromRGB(220, 220, 240),
    TEXT_DIM  = Color3.fromRGB(100, 105, 140),
    USER_BG   = Color3.fromRGB(28, 32, 55),
    AI_BG     = Color3.fromRGB(16, 34, 50),
    SUCCESS   = Color3.fromRGB(50, 200, 120),
    ERROR     = Color3.fromRGB(255, 80, 80),
    WARNING   = Color3.fromRGB(255, 180, 40),
    BORDER    = Color3.fromRGB(40, 45, 70),
    CODE_BG   = Color3.fromRGB(12, 12, 22),
}

-- ============================================================================
-- SERVICES
-- ============================================================================

local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")
local HttpService = game:GetService("HttpService")

local player = Players.LocalPlayer

-- Module loading (supports both sibling and child placement)
local API = require(script.Parent:FindFirstChild("api") or script:FindFirstChild("api"))
local ScannerModule = require(script.Parent:FindFirstChild("scanner") or script:FindFirstChild("scanner"))

local api = API.new({ baseUrl = CONFIG.BASE_URL, apiKey = CONFIG.API_KEY })
local scanner = ScannerModule.new(api)

-- ============================================================================
-- STATE
-- ============================================================================

local messageOrder = 0
local isSending = false
local isMinimized = false
local isConnected = false
local conversationHistory = {} -- last N messages for context
local scanResultCache = {} -- cached script scan results
local currentTab = "Chat"

-- ============================================================================
-- UTILITY
-- ============================================================================

local function trim(s: string): string
    return s:match("^%s*(.-)%s*$") or ""
end

local function maskKey(key: string): string
    if #key <= 8 then return string.rep("*", #key) end
    return key:sub(1, 4) .. string.rep("*", #key - 8) .. key:sub(-4)
end

local function tweenProp(obj, props, duration)
    duration = duration or 0.2
    TweenService:Create(obj, TweenInfo.new(duration, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), props):Play()
end

local function c3Hex(hex: string): Color3
    hex = hex:gsub("#", "")
    local r = tonumber(hex:sub(1, 2), 16) or 0
    local g = tonumber(hex:sub(3, 4), 16) or 0
    local b = tonumber(hex:sub(5, 6), 16) or 0
    return Color3.fromRGB(r, g, b)
end

-- ============================================================================
-- GUI CREATION
-- ============================================================================

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "PubAI"
screenGui.ResetOnSpawn = false
screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
screenGui.Parent = player:WaitForChild("PlayerGui")

-- Main frame
local mainFrame = Instance.new("Frame")
mainFrame.Name = "Main"
mainFrame.Size = UDim2.fromOffset(CONFIG.WIN_W, CONFIG.WIN_H)
mainFrame.Position = UDim2.new(0.5, -CONFIG.WIN_W / 2, 0.5, -CONFIG.WIN_H / 2)
mainFrame.BackgroundColor3 = C.BG
mainFrame.BorderSizePixel = 0
mainFrame.ClipsDescendants = true
mainFrame.Parent = screenGui

local mainCorner = Instance.new("UICorner")
mainCorner.CornerRadius = UDim.new(0, 12)
mainCorner.Parent = mainFrame

local mainStroke = Instance.new("UIStroke")
mainStroke.Color = C.BORDER
mainStroke.Thickness = 1
mainStroke.Parent = mainFrame

-- Drop shadow (subtle outer glow)
local shadow = Instance.new("ImageLabel")
shadow.Name = "Shadow"
shadow.Size = UDim2.new(1, 30, 1, 30)
shadow.Position = UDim2.fromOffset(-15, -15)
shadow.BackgroundTransparency = 1
shadow.ImageTransparency = 0.6
shadow.ImageColor3 = Color3.fromRGB(0, 0, 0)
shadow.Image = "rbxassetid://6014054950"
shadow.ScaleType = Enum.ScaleType.Slice
shadow.SliceCenter = Rect.new(49, 49, 450, 450)
shadow.ZIndex = -1
shadow.Parent = mainFrame

-- ============================================================================
-- TITLE BAR
-- ============================================================================

local titleBar = Instance.new("Frame")
titleBar.Name = "TitleBar"
titleBar.Size = UDim2.new(1, 0, 0, 38)
titleBar.BackgroundColor3 = C.PANEL
titleBar.BorderSizePixel = 0
titleBar.Parent = mainFrame

local titleCorner = Instance.new("UICorner")
titleCorner.CornerRadius = UDim.new(0, 12)
titleCorner.Parent = titleBar

-- Fill bottom corners of titlebar (so only top is rounded)
local titleFill = Instance.new("Frame")
titleFill.Size = UDim2.new(1, 0, 0, 14)
titleFill.Position = UDim2.new(0, 0, 1, -14)
titleFill.BackgroundColor3 = C.PANEL
titleFill.BorderSizePixel = 0
titleFill.Parent = titleBar

local titleLabel = Instance.new("TextLabel")
titleLabel.Size = UDim2.new(1, -120, 1, 0)
titleLabel.Position = UDim2.fromOffset(14, 0)
titleLabel.BackgroundTransparency = 1
titleLabel.Text = "Pub AI"
titleLabel.TextColor3 = C.ACCENT
titleLabel.Font = CONFIG.FONT_BOLD
titleLabel.TextSize = 17
titleLabel.TextXAlignment = Enum.TextXAlignment.Left
titleLabel.Parent = titleBar

-- Status indicator dot
local statusDot = Instance.new("Frame")
statusDot.Name = "Status"
statusDot.Size = UDim2.fromOffset(8, 8)
statusDot.Position = UDim2.new(0, 72, 0.5, -4)
statusDot.BackgroundColor3 = C.TEXT_DIM
statusDot.BorderSizePixel = 0
statusDot.Parent = titleBar
Instance.new("UICorner", statusDot).CornerRadius = UDim.new(1, 0)

-- Minimize button
local minimizeBtn = Instance.new("TextButton")
minimizeBtn.Size = UDim2.fromOffset(38, 38)
minimizeBtn.Position = UDim2.new(1, -76, 0, 0)
minimizeBtn.BackgroundTransparency = 1
minimizeBtn.Text = "-"
minimizeBtn.TextColor3 = C.TEXT_DIM
minimizeBtn.Font = CONFIG.FONT_BOLD
minimizeBtn.TextSize = 18
minimizeBtn.Parent = titleBar

-- Close button
local closeBtn = Instance.new("TextButton")
closeBtn.Size = UDim2.fromOffset(38, 38)
closeBtn.Position = UDim2.new(1, -38, 0, 0)
closeBtn.BackgroundTransparency = 1
closeBtn.Text = "X"
closeBtn.TextColor3 = C.TEXT_DIM
closeBtn.Font = CONFIG.FONT_BOLD
closeBtn.TextSize = 14
closeBtn.Parent = titleBar

-- ============================================================================
-- TAB BAR
-- ============================================================================

local tabBar = Instance.new("Frame")
tabBar.Name = "TabBar"
tabBar.Size = UDim2.new(1, 0, 0, 32)
tabBar.Position = UDim2.fromOffset(0, 38)
tabBar.BackgroundColor3 = C.PANEL
tabBar.BorderSizePixel = 0
tabBar.Parent = mainFrame

local tabSep = Instance.new("Frame")
tabSep.Size = UDim2.new(1, 0, 0, 1)
tabSep.Position = UDim2.new(0, 0, 1, -1)
tabSep.BackgroundColor3 = C.BORDER
tabSep.BorderSizePixel = 0
tabSep.Parent = tabBar

local tabLayout = Instance.new("UIListLayout")
tabLayout.FillDirection = Enum.FillDirection.Horizontal
tabLayout.Padding = UDim.new(0, 0)
tabLayout.Parent = tabBar

local TABS = { "Chat", "Scanner", "Settings" }
local tabButtons = {}
local tabPanels = {}

for _, name in ipairs(TABS) do
    local btn = Instance.new("TextButton")
    btn.Name = "Tab_" .. name
    btn.Size = UDim2.new(1 / #TABS, 0, 1, -1)
    btn.BackgroundColor3 = name == "Chat" and C.BG or C.PANEL
    btn.BackgroundTransparency = name == "Chat" and 0 or 0.5
    btn.BorderSizePixel = 0
    btn.Text = name
    btn.TextColor3 = name == "Chat" and C.ACCENT or C.TEXT_DIM
    btn.Font = CONFIG.FONT
    btn.TextSize = 13
    btn.Parent = tabBar
    tabButtons[name] = btn
end

-- Content area offset: titlebar (38) + tabbar (32) = 70
local CONTENT_TOP = 70

-- ============================================================================
-- CHAT PANEL
-- ============================================================================

local chatPanel = Instance.new("Frame")
chatPanel.Name = "ChatPanel"
chatPanel.Size = UDim2.new(1, 0, 1, -CONTENT_TOP - 52)
chatPanel.Position = UDim2.fromOffset(0, CONTENT_TOP)
chatPanel.BackgroundTransparency = 1
chatPanel.Parent = mainFrame
tabPanels["Chat"] = chatPanel

local chatScroll = Instance.new("ScrollingFrame")
chatScroll.Size = UDim2.new(1, -16, 1, 0)
chatScroll.Position = UDim2.fromOffset(8, 0)
chatScroll.BackgroundTransparency = 1
chatScroll.BorderSizePixel = 0
chatScroll.ScrollBarThickness = 4
chatScroll.ScrollBarImageColor3 = C.ACCENT
chatScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
chatScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
chatScroll.Parent = chatPanel

local chatLayout = Instance.new("UIListLayout")
chatLayout.Padding = UDim.new(0, 8)
chatLayout.SortOrder = Enum.SortOrder.LayoutOrder
chatLayout.Parent = chatScroll

-- Input area (fixed at bottom of main frame)
local inputFrame = Instance.new("Frame")
inputFrame.Name = "InputFrame"
inputFrame.Size = UDim2.new(1, -16, 0, 40)
inputFrame.Position = UDim2.new(0, 8, 1, -48)
inputFrame.BackgroundColor3 = C.INPUT_BG
inputFrame.BorderSizePixel = 0
inputFrame.Parent = mainFrame
Instance.new("UICorner", inputFrame).CornerRadius = UDim.new(0, 8)
Instance.new("UIStroke", inputFrame).Color = C.BORDER

local inputBox = Instance.new("TextBox")
inputBox.Size = UDim2.new(1, -50, 1, -8)
inputBox.Position = UDim2.fromOffset(10, 4)
inputBox.BackgroundTransparency = 1
inputBox.PlaceholderText = "Ask Pub AI anything..."
inputBox.PlaceholderColor3 = C.TEXT_DIM
inputBox.Text = ""
inputBox.TextColor3 = C.TEXT
inputBox.Font = CONFIG.FONT
inputBox.TextSize = 14
inputBox.TextXAlignment = Enum.TextXAlignment.Left
inputBox.ClearTextOnFocus = false
inputBox.Parent = inputFrame

local sendBtn = Instance.new("TextButton")
sendBtn.Size = UDim2.fromOffset(36, 32)
sendBtn.Position = UDim2.new(1, -40, 0, 4)
sendBtn.BackgroundColor3 = C.ACCENT
sendBtn.BorderSizePixel = 0
sendBtn.Text = ">"
sendBtn.TextColor3 = Color3.new(1, 1, 1)
sendBtn.Font = CONFIG.FONT_BOLD
sendBtn.TextSize = 16
sendBtn.Parent = inputFrame
Instance.new("UICorner", sendBtn).CornerRadius = UDim.new(0, 6)

-- ============================================================================
-- SCANNER PANEL
-- ============================================================================

local scanPanel = Instance.new("Frame")
scanPanel.Name = "ScanPanel"
scanPanel.Size = UDim2.new(1, 0, 1, -CONTENT_TOP - 8)
scanPanel.Position = UDim2.fromOffset(0, CONTENT_TOP)
scanPanel.BackgroundTransparency = 1
scanPanel.Visible = false
scanPanel.Parent = mainFrame
tabPanels["Scanner"] = scanPanel

-- Scan buttons row
local scanBtnRow = Instance.new("Frame")
scanBtnRow.Size = UDim2.new(1, -16, 0, 36)
scanBtnRow.Position = UDim2.fromOffset(8, 8)
scanBtnRow.BackgroundTransparency = 1
scanBtnRow.Parent = scanPanel

local scanBtnLayout = Instance.new("UIListLayout")
scanBtnLayout.FillDirection = Enum.FillDirection.Horizontal
scanBtnLayout.Padding = UDim.new(0, 8)
scanBtnLayout.Parent = scanBtnRow

local quickScanBtn = Instance.new("TextButton")
quickScanBtn.Name = "QuickScan"
quickScanBtn.Size = UDim2.new(0.48, 0, 1, 0)
quickScanBtn.BackgroundColor3 = C.ACCENT
quickScanBtn.BorderSizePixel = 0
quickScanBtn.Text = "Scan Workspace"
quickScanBtn.TextColor3 = Color3.new(1, 1, 1)
quickScanBtn.Font = CONFIG.FONT_BOLD
quickScanBtn.TextSize = 13
quickScanBtn.Parent = scanBtnRow
Instance.new("UICorner", quickScanBtn).CornerRadius = UDim.new(0, 8)

local deepScanBtn = Instance.new("TextButton")
deepScanBtn.Name = "DeepScan"
deepScanBtn.Size = UDim2.new(0.48, 0, 1, 0)
deepScanBtn.BackgroundColor3 = C.ACCENT2
deepScanBtn.BorderSizePixel = 0
deepScanBtn.Text = "Deep Scan (All)"
deepScanBtn.TextColor3 = Color3.new(1, 1, 1)
deepScanBtn.Font = CONFIG.FONT_BOLD
deepScanBtn.TextSize = 13
deepScanBtn.Parent = scanBtnRow
Instance.new("UICorner", deepScanBtn).CornerRadius = UDim.new(0, 8)

-- Scan status label
local scanStatus = Instance.new("TextLabel")
scanStatus.Size = UDim2.new(1, -16, 0, 20)
scanStatus.Position = UDim2.fromOffset(8, 50)
scanStatus.BackgroundTransparency = 1
scanStatus.Text = "Ready to scan"
scanStatus.TextColor3 = C.TEXT_DIM
scanStatus.Font = CONFIG.FONT
scanStatus.TextSize = 12
scanStatus.TextXAlignment = Enum.TextXAlignment.Left
scanStatus.Parent = scanPanel

-- Scan results scrolling list
local scanResults = Instance.new("ScrollingFrame")
scanResults.Size = UDim2.new(1, -16, 1, -80)
scanResults.Position = UDim2.fromOffset(8, 74)
scanResults.BackgroundTransparency = 1
scanResults.BorderSizePixel = 0
scanResults.ScrollBarThickness = 4
scanResults.ScrollBarImageColor3 = C.ACCENT
scanResults.CanvasSize = UDim2.new(0, 0, 0, 0)
scanResults.AutomaticCanvasSize = Enum.AutomaticSize.Y
scanResults.Parent = scanPanel

local scanResultLayout = Instance.new("UIListLayout")
scanResultLayout.Padding = UDim.new(0, 6)
scanResultLayout.SortOrder = Enum.SortOrder.LayoutOrder
scanResultLayout.Parent = scanResults

-- Script content viewer (overlay)
local viewerOverlay = Instance.new("Frame")
viewerOverlay.Name = "ScriptViewer"
viewerOverlay.Size = UDim2.new(1, -16, 1, -CONTENT_TOP - 16)
viewerOverlay.Position = UDim2.fromOffset(8, CONTENT_TOP + 8)
viewerOverlay.BackgroundColor3 = C.CODE_BG
viewerOverlay.BorderSizePixel = 0
viewerOverlay.Visible = false
viewerOverlay.ZIndex = 10
viewerOverlay.Parent = mainFrame
Instance.new("UICorner", viewerOverlay).CornerRadius = UDim.new(0, 8)
Instance.new("UIStroke", viewerOverlay).Color = C.BORDER

local viewerTitle = Instance.new("TextLabel")
viewerTitle.Size = UDim2.new(1, -50, 0, 28)
viewerTitle.Position = UDim2.fromOffset(10, 4)
viewerTitle.BackgroundTransparency = 1
viewerTitle.Text = "Script Viewer"
viewerTitle.TextColor3 = C.ACCENT
viewerTitle.Font = CONFIG.FONT_BOLD
viewerTitle.TextSize = 13
viewerTitle.TextXAlignment = Enum.TextXAlignment.Left
viewerTitle.ZIndex = 11
viewerTitle.Parent = viewerOverlay

local viewerClose = Instance.new("TextButton")
viewerClose.Size = UDim2.fromOffset(28, 28)
viewerClose.Position = UDim2.new(1, -34, 0, 4)
viewerClose.BackgroundTransparency = 1
viewerClose.Text = "X"
viewerClose.TextColor3 = C.TEXT_DIM
viewerClose.Font = CONFIG.FONT_BOLD
viewerClose.TextSize = 14
viewerClose.ZIndex = 11
viewerClose.Parent = viewerOverlay

local viewerScroll = Instance.new("ScrollingFrame")
viewerScroll.Size = UDim2.new(1, -8, 1, -36)
viewerScroll.Position = UDim2.fromOffset(4, 32)
viewerScroll.BackgroundTransparency = 1
viewerScroll.BorderSizePixel = 0
viewerScroll.ScrollBarThickness = 4
viewerScroll.ScrollBarImageColor3 = C.ACCENT
viewerScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
viewerScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
viewerScroll.ZIndex = 11
viewerScroll.Parent = viewerOverlay

local viewerContent = Instance.new("TextLabel")
viewerContent.Size = UDim2.new(1, -12, 0, 0)
viewerContent.Position = UDim2.fromOffset(6, 0)
viewerContent.AutomaticSize = Enum.AutomaticSize.Y
viewerContent.BackgroundTransparency = 1
viewerContent.Text = ""
viewerContent.TextColor3 = C.TEXT
viewerContent.Font = CONFIG.FONT_MONO
viewerContent.TextSize = 12
viewerContent.TextWrapped = true
viewerContent.TextXAlignment = Enum.TextXAlignment.Left
viewerContent.TextYAlignment = Enum.TextYAlignment.Top
viewerContent.ZIndex = 11
viewerContent.Parent = viewerScroll

viewerClose.MouseButton1Click:Connect(function()
    viewerOverlay.Visible = false
end)

-- ============================================================================
-- SETTINGS PANEL
-- ============================================================================

local settingsPanel = Instance.new("Frame")
settingsPanel.Name = "SettingsPanel"
settingsPanel.Size = UDim2.new(1, 0, 1, -CONTENT_TOP - 8)
settingsPanel.Position = UDim2.fromOffset(0, CONTENT_TOP)
settingsPanel.BackgroundTransparency = 1
settingsPanel.Visible = false
settingsPanel.Parent = mainFrame
tabPanels["Settings"] = settingsPanel

local function makeSettingRow(label: string, placeholder: string, yPos: number, parent: Instance, isSecret: boolean?): TextBox
    local lbl = Instance.new("TextLabel")
    lbl.Size = UDim2.new(1, -16, 0, 20)
    lbl.Position = UDim2.fromOffset(12, yPos)
    lbl.BackgroundTransparency = 1
    lbl.Text = label
    lbl.TextColor3 = C.TEXT_DIM
    lbl.Font = CONFIG.FONT
    lbl.TextSize = 12
    lbl.TextXAlignment = Enum.TextXAlignment.Left
    lbl.Parent = parent

    local box = Instance.new("TextBox")
    box.Size = UDim2.new(1, -24, 0, 34)
    box.Position = UDim2.fromOffset(12, yPos + 22)
    box.BackgroundColor3 = C.INPUT_BG
    box.BorderSizePixel = 0
    box.PlaceholderText = placeholder
    box.PlaceholderColor3 = C.TEXT_DIM
    box.Text = ""
    box.TextColor3 = C.TEXT
    box.Font = CONFIG.FONT_MONO
    box.TextSize = 12
    box.TextXAlignment = Enum.TextXAlignment.Left
    box.ClearTextOnFocus = false
    box.Parent = parent
    Instance.new("UICorner", box).CornerRadius = UDim.new(0, 6)
    Instance.new("UIStroke", box).Color = C.BORDER

    local pad = Instance.new("UIPadding", box)
    pad.PaddingLeft = UDim.new(0, 10)
    pad.PaddingRight = UDim.new(0, 10)

    return box
end

local apiKeyBox = makeSettingRow("API Key", "pub_xxxxxxxxxxxx", 12, settingsPanel, true)
-- Store the real key separately; display masked version
local realApiKey = CONFIG.API_KEY ~= "YOUR_API_KEY_HERE" and CONFIG.API_KEY or ""
apiKeyBox.Text = realApiKey ~= "" and maskKey(realApiKey) or ""

-- When user focuses the API key box, show real value for editing; when they leave, mask it
local isEditingKey = false
apiKeyBox.Focused:Connect(function()
    isEditingKey = true
    apiKeyBox.Text = realApiKey
end)
apiKeyBox.FocusLost:Connect(function()
    isEditingKey = false
    realApiKey = trim(apiKeyBox.Text)
    apiKeyBox.Text = realApiKey ~= "" and maskKey(realApiKey) or ""
end)

local baseUrlBox = makeSettingRow("Backend URL", "https://your-backend.railway.app", 76, settingsPanel)
baseUrlBox.Text = CONFIG.BASE_URL

-- Theme selector
local themeLabel = Instance.new("TextLabel")
themeLabel.Size = UDim2.new(1, -24, 0, 20)
themeLabel.Position = UDim2.fromOffset(12, 140)
themeLabel.BackgroundTransparency = 1
themeLabel.Text = "Accent Color"
themeLabel.TextColor3 = C.TEXT_DIM
themeLabel.Font = CONFIG.FONT
themeLabel.TextSize = 12
themeLabel.TextXAlignment = Enum.TextXAlignment.Left
themeLabel.Parent = settingsPanel

local themeRow = Instance.new("Frame")
themeRow.Size = UDim2.new(1, -24, 0, 30)
themeRow.Position = UDim2.fromOffset(12, 162)
themeRow.BackgroundTransparency = 1
themeRow.Parent = settingsPanel

local themeLayout = Instance.new("UIListLayout")
themeLayout.FillDirection = Enum.FillDirection.Horizontal
themeLayout.Padding = UDim.new(0, 8)
themeLayout.Parent = themeRow

local THEME_COLORS = {
    { name = "Blue",   color = Color3.fromRGB(0, 170, 255) },
    { name = "Purple", color = Color3.fromRGB(130, 80, 255) },
    { name = "Green",  color = Color3.fromRGB(50, 200, 120) },
    { name = "Red",    color = Color3.fromRGB(255, 80, 80) },
    { name = "Gold",   color = Color3.fromRGB(255, 200, 50) },
}

for _, theme in ipairs(THEME_COLORS) do
    local swatch = Instance.new("TextButton")
    swatch.Size = UDim2.fromOffset(30, 30)
    swatch.BackgroundColor3 = theme.color
    swatch.BorderSizePixel = 0
    swatch.Text = ""
    swatch.Parent = themeRow
    Instance.new("UICorner", swatch).CornerRadius = UDim.new(0, 6)

    swatch.MouseButton1Click:Connect(function()
        C.ACCENT = theme.color
        titleLabel.TextColor3 = theme.color
        chatScroll.ScrollBarImageColor3 = theme.color
        scanResults.ScrollBarImageColor3 = theme.color
        statusDot.BackgroundColor3 = isConnected and C.SUCCESS or C.ERROR
        sendBtn.BackgroundColor3 = theme.color
        quickScanBtn.BackgroundColor3 = theme.color
    end)
end

local saveSettingsBtn = Instance.new("TextButton")
saveSettingsBtn.Size = UDim2.new(1, -24, 0, 38)
saveSettingsBtn.Position = UDim2.fromOffset(12, 204)
saveSettingsBtn.BackgroundColor3 = C.SUCCESS
saveSettingsBtn.BorderSizePixel = 0
saveSettingsBtn.Text = "Save & Connect"
saveSettingsBtn.TextColor3 = Color3.new(1, 1, 1)
saveSettingsBtn.Font = CONFIG.FONT_BOLD
saveSettingsBtn.TextSize = 14
saveSettingsBtn.Parent = settingsPanel
Instance.new("UICorner", saveSettingsBtn).CornerRadius = UDim.new(0, 8)

local connStatus = Instance.new("TextLabel")
connStatus.Size = UDim2.new(1, -24, 0, 24)
connStatus.Position = UDim2.fromOffset(12, 250)
connStatus.BackgroundTransparency = 1
connStatus.Text = ""
connStatus.TextColor3 = C.TEXT_DIM
connStatus.Font = CONFIG.FONT
connStatus.TextSize = 12
connStatus.TextXAlignment = Enum.TextXAlignment.Left
connStatus.Parent = settingsPanel

-- Persistence info
local persistNote = Instance.new("TextLabel")
persistNote.Size = UDim2.new(1, -24, 0, 40)
persistNote.Position = UDim2.fromOffset(12, 280)
persistNote.BackgroundTransparency = 1
persistNote.Text = "Settings persist via _G for this session.\nGenerate API keys at the Pub AI web panel."
persistNote.TextColor3 = C.TEXT_DIM
persistNote.Font = CONFIG.FONT
persistNote.TextSize = 11
persistNote.TextWrapped = true
persistNote.TextXAlignment = Enum.TextXAlignment.Left
persistNote.Parent = settingsPanel

-- ============================================================================
-- CHAT LOGIC
-- ============================================================================

local function addMessage(role: string, text: string): Frame
    messageOrder += 1

    local bubble = Instance.new("Frame")
    bubble.Name = "Msg_" .. messageOrder
    bubble.Size = UDim2.new(1, 0, 0, 0)
    bubble.AutomaticSize = Enum.AutomaticSize.Y
    bubble.BackgroundColor3 = role == "user" and C.USER_BG or C.AI_BG
    bubble.BorderSizePixel = 0
    bubble.LayoutOrder = messageOrder
    bubble.Parent = chatScroll
    Instance.new("UICorner", bubble).CornerRadius = UDim.new(0, 8)

    local bpad = Instance.new("UIPadding", bubble)
    bpad.PaddingTop = UDim.new(0, 8)
    bpad.PaddingBottom = UDim.new(0, 8)
    bpad.PaddingLeft = UDim.new(0, 10)
    bpad.PaddingRight = UDim.new(0, 10)

    local roleLabel = Instance.new("TextLabel")
    roleLabel.Size = UDim2.new(1, 0, 0, 16)
    roleLabel.BackgroundTransparency = 1
    roleLabel.Text = role == "user" and player.Name or "Pub AI"
    roleLabel.TextColor3 = role == "user" and C.ACCENT2 or C.ACCENT
    roleLabel.Font = CONFIG.FONT_BOLD
    roleLabel.TextSize = 11
    roleLabel.TextXAlignment = Enum.TextXAlignment.Left
    roleLabel.Parent = bubble

    local content = Instance.new("TextLabel")
    content.Name = "Content"
    content.Size = UDim2.new(1, 0, 0, 0)
    content.Position = UDim2.fromOffset(0, 18)
    content.AutomaticSize = Enum.AutomaticSize.Y
    content.BackgroundTransparency = 1
    content.Text = text
    content.TextColor3 = C.TEXT
    content.Font = CONFIG.FONT
    content.TextSize = 13
    content.TextWrapped = true
    content.TextXAlignment = Enum.TextXAlignment.Left
    content.RichText = true
    content.Parent = bubble

    -- Auto-scroll to bottom
    task.defer(function()
        chatScroll.CanvasPosition = Vector2.new(0, chatScroll.AbsoluteCanvasSize.Y)
    end)

    return bubble
end

-- ============================================================================
-- AI COMMAND PARSING & SELF-MODIFICATION
-- ============================================================================

local guiComponents = {
    mainFrame = mainFrame,
    titleBar = titleBar,
    titleLabel = titleLabel,
    chatPanel = chatPanel,
    scanPanel = scanPanel,
    settingsPanel = settingsPanel,
    inputBox = inputBox,
    sendBtn = sendBtn,
    statusDot = statusDot,
}

local function executeGuiModify(params: string)
    -- Parse "property=value" pairs
    for pair in params:gmatch("[^,]+") do
        local prop, val = pair:match("^%s*(.-)%s*=%s*(.-)%s*$")
        if prop and val then
            -- Handle known modification targets
            if prop == "accent_color" or prop == "color" then
                local newColor = c3Hex(val)
                C.ACCENT = newColor
                titleLabel.TextColor3 = newColor
                sendBtn.BackgroundColor3 = newColor
                quickScanBtn.BackgroundColor3 = newColor
                chatScroll.ScrollBarImageColor3 = newColor
            elseif prop == "title" then
                titleLabel.Text = val
            elseif prop == "bg_color" then
                local newColor = c3Hex(val)
                C.BG = newColor
                mainFrame.BackgroundColor3 = newColor
            elseif prop == "size" then
                local w, h = val:match("(%d+)x(%d+)")
                if w and h then
                    mainFrame.Size = UDim2.fromOffset(tonumber(w), tonumber(h))
                end
            elseif prop == "placeholder" then
                inputBox.PlaceholderText = val
            end
        end
    end
end

local function executeScanCommand(target: string)
    -- Switch to scanner tab and trigger a scan
    for tabName, panel in pairs(tabPanels) do
        panel.Visible = (tabName == "Scanner")
    end
    for tabName, tabBtn in pairs(tabButtons) do
        tabBtn.BackgroundColor3 = tabName == "Scanner" and C.BG or C.PANEL
        tabBtn.BackgroundTransparency = tabName == "Scanner" and 0 or 0.5
        tabBtn.TextColor3 = tabName == "Scanner" and C.ACCENT or C.TEXT_DIM
    end
    currentTab = "Scanner"
    -- The scan will be triggered by the user clicking the button
    scanStatus.Text = "AI requested scan: " .. target
end

local function executeCodeCommand(code: string)
    local ok, err = pcall(function()
        local fn = loadstring(code)
        if fn then fn() end
    end)
    if not ok then
        addMessage("assistant", '<font color="#ff5050">Code execution error: ' .. tostring(err) .. "</font>")
    end
end

local function processAICommands(response: string): string
    -- Parse and execute embedded AI commands, strip them from displayed text
    local cleaned = response

    -- [MODIFY_GUI: property=value, property2=value2]
    cleaned = cleaned:gsub("%[MODIFY_GUI:%s*(.-)%]", function(params)
        task.spawn(function() executeGuiModify(params) end)
        return ""
    end)

    -- [SCAN: target]
    cleaned = cleaned:gsub("%[SCAN:%s*(.-)%]", function(target)
        task.spawn(function() executeScanCommand(target) end)
        return ""
    end)

    -- [EXECUTE: lua_code]
    cleaned = cleaned:gsub("%[EXECUTE:%s*(.-)%]", function(code)
        task.spawn(function() executeCodeCommand(code) end)
        return ""
    end)

    return trim(cleaned)
end

-- ============================================================================
-- MESSAGE SENDING
-- ============================================================================

local function sendMessage()
    local text = trim(inputBox.Text)
    if text == "" or isSending then return end

    isSending = true
    inputBox.Text = ""
    addMessage("user", text)

    -- Track in conversation history
    table.insert(conversationHistory, { role = "user", content = text })
    if #conversationHistory > CONFIG.MAX_HISTORY then
        table.remove(conversationHistory, 1)
    end

    -- Show typing indicator
    local typing = addMessage("assistant", '<font color="rgb(100,105,140)">Thinking...</font>')

    -- Build context
    local context = {
        place_id = game.PlaceId,
        player_name = player.Name,
        gui_info = "Pub AI Roblox Client, self-aware GUI, can modify itself via commands",
    }

    local ok, err = pcall(function()
        local gameName = game:GetService("MarketplaceService"):GetProductInfo(game.PlaceId).Name
        context.game_name = gameName
    end)

    local success, data = api:chat(text, context)

    -- Remove typing indicator
    typing:Destroy()

    if success and data.response then
        local response = data.response
        -- Process any embedded AI commands
        local displayText = processAICommands(response)
        if displayText ~= "" then
            addMessage("assistant", displayText)
        end

        -- Track in history
        table.insert(conversationHistory, { role = "assistant", content = data.response })
        if #conversationHistory > CONFIG.MAX_HISTORY then
            table.remove(conversationHistory, 1)
        end
    else
        local errMsg = data and (data.error or data.detail) or "Connection failed"
        addMessage("assistant", '<font color="#ff5050">Error: ' .. tostring(errMsg) .. "</font>")
    end

    isSending = false
end

-- ============================================================================
-- SCANNER LOGIC
-- ============================================================================

local function clearScanResults()
    for _, child in ipairs(scanResults:GetChildren()) do
        if child:IsA("Frame") then child:Destroy() end
    end
    scanResultCache = {}
end

local function createScanResultRow(info, index: number)
    local row = Instance.new("Frame")
    row.Name = "Result_" .. index
    row.Size = UDim2.new(1, 0, 0, 0)
    row.AutomaticSize = Enum.AutomaticSize.Y
    row.BackgroundColor3 = C.PANEL
    row.BorderSizePixel = 0
    row.LayoutOrder = index
    row.Parent = scanResults
    Instance.new("UICorner", row).CornerRadius = UDim.new(0, 6)
    Instance.new("UIStroke", row).Color = C.BORDER

    local rpad = Instance.new("UIPadding", row)
    rpad.PaddingTop = UDim.new(0, 6)
    rpad.PaddingBottom = UDim.new(0, 6)
    rpad.PaddingLeft = UDim.new(0, 10)
    rpad.PaddingRight = UDim.new(0, 10)

    -- Script name + class badge
    local nameLabel = Instance.new("TextLabel")
    nameLabel.Size = UDim2.new(1, -120, 0, 18)
    nameLabel.BackgroundTransparency = 1
    nameLabel.Text = info.name
    nameLabel.TextColor3 = C.ACCENT
    nameLabel.Font = CONFIG.FONT_BOLD
    nameLabel.TextSize = 12
    nameLabel.TextXAlignment = Enum.TextXAlignment.Left
    nameLabel.TextTruncate = Enum.TextTruncate.AtEnd
    nameLabel.Parent = row

    -- Class badge
    local classBadge = Instance.new("TextLabel")
    classBadge.Size = UDim2.fromOffset(80, 16)
    classBadge.Position = UDim2.new(1, -80, 0, 1)
    classBadge.BackgroundColor3 = C.INPUT_BG
    classBadge.BorderSizePixel = 0
    classBadge.Text = info.className or "Script"
    classBadge.TextColor3 = C.TEXT_DIM
    classBadge.Font = CONFIG.FONT
    classBadge.TextSize = 10
    classBadge.Parent = row
    Instance.new("UICorner", classBadge).CornerRadius = UDim.new(0, 4)

    -- Path + line count
    local pathLabel = Instance.new("TextLabel")
    pathLabel.Size = UDim2.new(1, 0, 0, 14)
    pathLabel.Position = UDim2.fromOffset(0, 20)
    pathLabel.BackgroundTransparency = 1
    pathLabel.TextColor3 = C.TEXT_DIM
    pathLabel.Font = CONFIG.FONT
    pathLabel.TextSize = 10
    pathLabel.TextXAlignment = Enum.TextXAlignment.Left
    pathLabel.TextTruncate = Enum.TextTruncate.AtEnd
    pathLabel.Parent = row

    -- Use fullname or path
    local pathStr = info.path or info.name
    local lineStr = info.lineCount and info.lineCount > 0 and string.format(" | %d lines", info.lineCount) or ""
    pathLabel.Text = pathStr .. lineStr

    -- Buttons row
    local btnRow = Instance.new("Frame")
    btnRow.Size = UDim2.new(1, 0, 0, 26)
    btnRow.Position = UDim2.fromOffset(0, 38)
    btnRow.BackgroundTransparency = 1
    btnRow.Parent = row

    local btnLayout = Instance.new("UIListLayout")
    btnLayout.FillDirection = Enum.FillDirection.Horizontal
    btnLayout.Padding = UDim.new(0, 6)
    btnLayout.Parent = btnRow

    -- View source button
    if info.source and #info.source > 0 then
        local viewBtn = Instance.new("TextButton")
        viewBtn.Size = UDim2.fromOffset(70, 24)
        viewBtn.BackgroundColor3 = C.INPUT_BG
        viewBtn.BorderSizePixel = 0
        viewBtn.Text = "View"
        viewBtn.TextColor3 = C.TEXT
        viewBtn.Font = CONFIG.FONT
        viewBtn.TextSize = 11
        viewBtn.Parent = btnRow
        Instance.new("UICorner", viewBtn).CornerRadius = UDim.new(0, 4)

        viewBtn.MouseButton1Click:Connect(function()
            viewerTitle.Text = info.name
            viewerContent.Text = info.source
            viewerOverlay.Visible = true
        end)
    end

    -- Scan with AI button
    if info.source and #info.source > 0 then
        local analyzeBtn = Instance.new("TextButton")
        analyzeBtn.Size = UDim2.fromOffset(80, 24)
        analyzeBtn.BackgroundColor3 = C.ACCENT
        analyzeBtn.BorderSizePixel = 0
        analyzeBtn.Text = "Analyze"
        analyzeBtn.TextColor3 = Color3.new(1, 1, 1)
        analyzeBtn.Font = CONFIG.FONT
        analyzeBtn.TextSize = 11
        analyzeBtn.Parent = btnRow
        Instance.new("UICorner", analyzeBtn).CornerRadius = UDim.new(0, 4)

        analyzeBtn.MouseButton1Click:Connect(function()
            analyzeBtn.Text = "..."
            analyzeBtn.BackgroundColor3 = C.TEXT_DIM
            local ok, data = api:scan(info.source, info.name)
            analyzeBtn.Text = "Done"
            analyzeBtn.BackgroundColor3 = C.SUCCESS

            if ok and data.analysis then
                -- Show analysis in chat tab
                addMessage("assistant", '<font color="#00aaff">[Scan: ' .. info.name .. ']</font>\n' .. data.analysis)
            end

            task.wait(1)
            analyzeBtn.Text = "Analyze"
            analyzeBtn.BackgroundColor3 = C.ACCENT
        end)
    end

    -- Decompile button (always available)
    local decompBtn = Instance.new("TextButton")
    decompBtn.Size = UDim2.fromOffset(90, 24)
    decompBtn.BackgroundColor3 = C.ACCENT2
    decompBtn.BorderSizePixel = 0
    decompBtn.Text = "Decompile"
    decompBtn.TextColor3 = Color3.new(1, 1, 1)
    decompBtn.Font = CONFIG.FONT
    decompBtn.TextSize = 11
    decompBtn.Parent = btnRow
    Instance.new("UICorner", decompBtn).CornerRadius = UDim.new(0, 4)

    decompBtn.MouseButton1Click:Connect(function()
        decompBtn.Text = "..."
        decompBtn.BackgroundColor3 = C.TEXT_DIM

        local src = info.source or ""
        local ok, data = api:decompile(src)

        if ok and data.decompiled then
            viewerTitle.Text = info.name .. " (decompiled)"
            viewerContent.Text = data.decompiled
            viewerOverlay.Visible = true
        else
            addMessage("assistant", '<font color="#ff5050">Decompile failed for ' .. info.name .. "</font>")
        end

        decompBtn.Text = "Decompile"
        decompBtn.BackgroundColor3 = C.ACCENT2
    end)
end

local function runScan(deep: boolean)
    clearScanResults()

    local btnRef = deep and deepScanBtn or quickScanBtn
    local originalText = btnRef.Text
    btnRef.Text = "Scanning..."
    btnRef.BackgroundColor3 = C.TEXT_DIM

    scanStatus.Text = deep and "Deep scanning all descendants..." or "Scanning workspace scripts..."

    task.spawn(function()
        local scripts
        if deep then
            scripts = scanner:getScripts(game)
        else
            scripts = scanner:getScripts(game:GetService("Workspace"))
        end

        if #scripts == 0 then
            scanStatus.Text = "No accessible scripts found"
            btnRef.Text = originalText
            btnRef.BackgroundColor3 = deep and C.ACCENT2 or C.ACCENT
            return
        end

        scanStatus.Text = string.format("Found %d script(s)", #scripts)
        scanResultCache = scripts

        for i, info in ipairs(scripts) do
            -- Build display info
            local displayInfo = {
                name = info.name,
                className = info.instance and info.instance.ClassName or "Script",
                path = info.name, -- getFullName is already in name
                source = info.source or "",
                lineCount = 0,
            }

            if displayInfo.source and #displayInfo.source > 0 then
                local count = 1
                for _ in displayInfo.source:gmatch("\n") do
                    count += 1
                end
                displayInfo.lineCount = count
            end

            createScanResultRow(displayInfo, i)

            -- Yield periodically to avoid freezing
            if i % 10 == 0 then
                task.wait()
            end
        end

        btnRef.Text = originalText
        btnRef.BackgroundColor3 = deep and C.ACCENT2 or C.ACCENT
    end)
end

-- ============================================================================
-- EVENT WIRING
-- ============================================================================

-- Send on button click or Enter key
sendBtn.MouseButton1Click:Connect(sendMessage)
inputBox.FocusLost:Connect(function(enterPressed)
    if enterPressed then
        sendMessage()
    end
end)

-- Tab switching
for name, btn in pairs(tabButtons) do
    btn.MouseButton1Click:Connect(function()
        currentTab = name
        for tabName, panel in pairs(tabPanels) do
            panel.Visible = (tabName == name)
        end
        for tabName, tabBtn in pairs(tabButtons) do
            local isActive = (tabName == name)
            tweenProp(tabBtn, {
                BackgroundColor3 = isActive and C.BG or C.PANEL,
                BackgroundTransparency = isActive and 0 or 0.5,
                TextColor3 = isActive and C.ACCENT or C.TEXT_DIM,
            }, 0.15)
        end
        -- Show/hide input bar (only for chat)
        inputFrame.Visible = (name == "Chat")
    end)
end

-- Close button destroys GUI
closeBtn.MouseButton1Click:Connect(function()
    screenGui:Destroy()
end)

-- Minimize button
local fullSize = UDim2.fromOffset(CONFIG.WIN_W, CONFIG.WIN_H)
local minSize = UDim2.fromOffset(CONFIG.WIN_W, 38)

minimizeBtn.MouseButton1Click:Connect(function()
    isMinimized = not isMinimized
    if isMinimized then
        tweenProp(mainFrame, { Size = minSize }, 0.2)
        minimizeBtn.Text = "+"
    else
        tweenProp(mainFrame, { Size = fullSize }, 0.2)
        minimizeBtn.Text = "-"
    end
end)

-- Dragging
local dragging = false
local dragStart, startPos

titleBar.InputBegan:Connect(function(input)
    if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.Touch then
        dragging = true
        dragStart = input.Position
        startPos = mainFrame.Position
    end
end)

titleBar.InputEnded:Connect(function(input)
    if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.Touch then
        dragging = false
    end
end)

UserInputService.InputChanged:Connect(function(input)
    if dragging and (input.UserInputType == Enum.UserInputType.MouseMovement or input.UserInputType == Enum.UserInputType.Touch) then
        local delta = input.Position - dragStart
        mainFrame.Position = UDim2.new(
            startPos.X.Scale, startPos.X.Offset + delta.X,
            startPos.Y.Scale, startPos.Y.Offset + delta.Y
        )
    end
end)

-- Settings save
saveSettingsBtn.MouseButton1Click:Connect(function()
    local newKey = realApiKey
    local newUrl = trim(baseUrlBox.Text)

    if newKey ~= "" then
        api:setApiKey(newKey)
        -- Persist via _G
        _G.PubAI_ApiKey = newKey
    end
    if newUrl ~= "" then
        api:setBaseUrl(newUrl)
        _G.PubAI_BaseUrl = newUrl
    end

    -- Test connection
    connStatus.Text = "Testing connection..."
    connStatus.TextColor3 = C.TEXT_DIM
    saveSettingsBtn.BackgroundColor3 = C.TEXT_DIM

    task.spawn(function()
        local ok, data = api:status()
        if ok and data.status == "online" then
            connStatus.Text = "Connected! Features: " .. table.concat(data.features or {}, ", ")
            connStatus.TextColor3 = C.SUCCESS
            statusDot.BackgroundColor3 = C.SUCCESS
            isConnected = true
        else
            connStatus.Text = "Connection failed: " .. tostring(data and data.error or "Check URL")
            connStatus.TextColor3 = C.ERROR
            statusDot.BackgroundColor3 = C.ERROR
            isConnected = false
        end
        saveSettingsBtn.BackgroundColor3 = C.SUCCESS
    end)
end)

-- Scanner buttons
quickScanBtn.MouseButton1Click:Connect(function()
    runScan(false)
end)

deepScanBtn.MouseButton1Click:Connect(function()
    runScan(true)
end)

-- Button hover effects
local function addHover(btn: TextButton, baseColor: Color3)
    btn.MouseEnter:Connect(function()
        tweenProp(btn, { BackgroundColor3 = baseColor:Lerp(Color3.new(1, 1, 1), 0.15) }, 0.1)
    end)
    btn.MouseLeave:Connect(function()
        tweenProp(btn, { BackgroundColor3 = baseColor }, 0.1)
    end)
end

addHover(sendBtn, C.ACCENT)
addHover(quickScanBtn, C.ACCENT)
addHover(deepScanBtn, C.ACCENT2)
addHover(saveSettingsBtn, C.SUCCESS)

-- ============================================================================
-- HEALTH CHECK POLLING
-- ============================================================================

task.spawn(function()
    while screenGui.Parent do
        task.wait(CONFIG.HEALTH_INTERVAL)
        local ok, data = pcall(function()
            return api:status()
        end)
        if ok then
            local success, result = data, nil
            -- api:status() returns two values; pcall wraps differently
            -- Re-call properly
            local s, d = api:status()
            if s and d and d.status == "online" then
                if not isConnected then
                    statusDot.BackgroundColor3 = C.SUCCESS
                    isConnected = true
                end
            else
                if isConnected then
                    statusDot.BackgroundColor3 = C.ERROR
                    isConnected = false
                end
            end
        end
    end
end)

-- ============================================================================
-- INIT
-- ============================================================================

-- Restore persisted settings
if _G.PubAI_ApiKey and _G.PubAI_ApiKey ~= "" then
    realApiKey = _G.PubAI_ApiKey
    api:setApiKey(realApiKey)
    apiKeyBox.Text = maskKey(realApiKey)
end

if _G.PubAI_BaseUrl and _G.PubAI_BaseUrl ~= "" then
    api:setBaseUrl(_G.PubAI_BaseUrl)
    baseUrlBox.Text = _G.PubAI_BaseUrl
end

-- Initial connection check
task.spawn(function()
    task.wait(1)
    local ok, data = api:status()
    if ok and data.status == "online" then
        statusDot.BackgroundColor3 = C.SUCCESS
        isConnected = true
        addMessage("assistant", "Connected to Pub AI. I'm ready — ask me anything about Lua, Roblox, or scan your workspace scripts.")
    else
        statusDot.BackgroundColor3 = C.ERROR
        isConnected = false
        addMessage("assistant", '<font color="#ff5050">Not connected.</font> Open the <font color="#00aaff">Settings</font> tab to configure your API key and backend URL.')
    end
end)
