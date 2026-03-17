--[[
    PubAI NPC — ServerScript
    Place in ServerScriptService in Roblox Studio

    SETUP:
    1. Enable HttpService in Game Settings > Security
    2. Place this script in ServerScriptService
    3. Place npc_actions.lua as a ModuleScript INSIDE this script (or in ServerScriptService)
    4. Run pubai_relay.py on your PC first
]]

-- ============================================================================
-- CONFIG
-- ============================================================================

local CONFIG = {
    BASE_URL    = "https://pubai-relay-production.up.railway.app",
    OWNER       = "obinofue1",
    NPC_NAME    = "PubAI",
    SPAWN_POS   = Vector3.new(0, 5, 0),
    CHAT_COLOR  = Color3.fromRGB(0, 170, 255),
}

-- ============================================================================
-- SERVICES
-- ============================================================================

local Players       = game:GetService("Players")
local HttpService   = game:GetService("HttpService")
local RunService    = game:GetService("RunService")
local Chat          = game:GetService("Chat")
local Debris        = game:GetService("Debris")
local Lighting      = game:GetService("Lighting")

-- Load actions module — try as child first, then sibling
local Actions = require(script:FindFirstChild("npc_actions") or script.Parent:FindFirstChild("npc_actions"))

-- ============================================================================
-- STATE
-- ============================================================================

local npcModel = nil
local npcHumanoid = nil
local isFollowing = false
local followTarget = nil
local conversationId = nil

-- ============================================================================
-- CREATE NPC CHARACTER
-- ============================================================================

local function createNPC()
    if npcModel then pcall(function() npcModel:Destroy() end) end

    local model = Instance.new("Model")
    model.Name = CONFIG.NPC_NAME

    -- Helper: make a body part
    local function limb(name, size, offset, color)
        local p = Instance.new("Part")
        p.Name = name
        p.Size = size
        p.Position = CONFIG.SPAWN_POS + offset
        p.BrickColor = BrickColor.new(color)
        p.TopSurface = Enum.SurfaceType.Smooth
        p.BottomSurface = Enum.SurfaceType.Smooth
        p.Anchored = false
        p.Parent = model
        return p
    end

    local head     = limb("Head",           Vector3.new(2, 1, 1),    Vector3.new(0, 4.5, 0),  "Institutional white")
    local torso    = limb("Torso",          Vector3.new(2, 2, 1),    Vector3.new(0, 3, 0),    "Really black")
    local leftArm  = limb("Left Arm",      Vector3.new(1, 2, 1),    Vector3.new(-1.5, 3, 0), "Institutional white")
    local rightArm = limb("Right Arm",     Vector3.new(1, 2, 1),    Vector3.new(1.5, 3, 0),  "Institutional white")
    local leftLeg  = limb("Left Leg",      Vector3.new(1, 2, 1),    Vector3.new(-0.5, 1, 0), "Dark stone grey")
    local rightLeg = limb("Right Leg",     Vector3.new(1, 2, 1),    Vector3.new(0.5, 1, 0),  "Dark stone grey")

    -- HumanoidRootPart
    local hrp = Instance.new("Part")
    hrp.Name = "HumanoidRootPart"
    hrp.Size = Vector3.new(2, 2, 1)
    hrp.Position = CONFIG.SPAWN_POS + Vector3.new(0, 3, 0)
    hrp.Transparency = 1
    hrp.Anchored = false
    hrp.Parent = model

    -- Face
    local face = Instance.new("Decal")
    face.Name = "face"
    face.Texture = "rbxasset://textures/face.png"
    face.Face = Enum.NormalId.Front
    face.Parent = head

    local headMesh = Instance.new("SpecialMesh")
    headMesh.MeshType = Enum.MeshType.Head
    headMesh.Scale = Vector3.new(1.25, 1.25, 1.25)
    headMesh.Parent = head

    -- Logo on torso
    local logo = Instance.new("SurfaceGui")
    logo.Face = Enum.NormalId.Front
    logo.Parent = torso
    local txt = Instance.new("TextLabel")
    txt.Size = UDim2.new(1, 0, 1, 0)
    txt.BackgroundTransparency = 1
    txt.Text = "P+"
    txt.TextColor3 = CONFIG.CHAT_COLOR
    txt.TextScaled = true
    txt.Font = Enum.Font.GothamBold
    txt.Parent = logo

    -- Humanoid
    local humanoid = Instance.new("Humanoid")
    humanoid.DisplayName = CONFIG.NPC_NAME
    humanoid.MaxHealth = math.huge
    humanoid.Health = math.huge
    humanoid.WalkSpeed = 16
    humanoid.JumpPower = 50
    humanoid.Parent = model

    -- Motor6D joints
    local function weld(name, p0, p1, c0, c1)
        local m = Instance.new("Motor6D")
        m.Name = name
        m.Part0 = p0
        m.Part1 = p1
        m.C0 = c0
        m.C1 = c1 or CFrame.new()
        m.Parent = p0
    end

    weld("RootJoint",       hrp,   torso,    CFrame.new(0, 0, 0))
    weld("Neck",            torso, head,     CFrame.new(0, 1, 0),    CFrame.new(0, -0.5, 0))
    weld("Left Shoulder",   torso, leftArm,  CFrame.new(-1, 0.5, 0), CFrame.new(0.5, 0.5, 0))
    weld("Right Shoulder",  torso, rightArm, CFrame.new(1, 0.5, 0),  CFrame.new(-0.5, 0.5, 0))
    weld("Left Hip",        torso, leftLeg,  CFrame.new(-0.5, -1, 0),CFrame.new(0, 1, 0))
    weld("Right Hip",       torso, rightLeg, CFrame.new(0.5, -1, 0), CFrame.new(0, 1, 0))

    model.PrimaryPart = hrp
    model.Parent = workspace

    -- Nametag
    local bb = Instance.new("BillboardGui")
    bb.Adornee = head
    bb.Size = UDim2.new(0, 200, 0, 50)
    bb.StudsOffset = Vector3.new(0, 2, 0)
    bb.AlwaysOnTop = true
    bb.Parent = head
    local nameLabel = Instance.new("TextLabel")
    nameLabel.Size = UDim2.new(1, 0, 1, 0)
    nameLabel.BackgroundTransparency = 1
    nameLabel.Text = CONFIG.NPC_NAME
    nameLabel.TextColor3 = CONFIG.CHAT_COLOR
    nameLabel.TextStrokeTransparency = 0.5
    nameLabel.TextStrokeColor3 = Color3.new(0, 0, 0)
    nameLabel.TextScaled = true
    nameLabel.Font = Enum.Font.GothamBold
    nameLabel.Parent = bb

    -- Glow particles
    local particles = Instance.new("ParticleEmitter")
    particles.Color = ColorSequence.new(CONFIG.CHAT_COLOR)
    particles.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.3), NumberSequenceKeypoint.new(1, 0)})
    particles.Transparency = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.5), NumberSequenceKeypoint.new(1, 1)})
    particles.Lifetime = NumberRange.new(0.5, 1)
    particles.Rate = 15
    particles.Speed = NumberRange.new(0.5, 1)
    particles.SpreadAngle = Vector2.new(360, 360)
    particles.Parent = hrp

    -- Proximity prompt
    local prox = Instance.new("ProximityPrompt")
    prox.ActionText = "Talk to PubAI"
    prox.ObjectText = "PubAI"
    prox.MaxActivationDistance = 15
    prox.HoldDuration = 0
    prox.Parent = hrp
    prox.Triggered:Connect(function(player)
        if player.Name == CONFIG.OWNER then
            npcSay("What's up boss? Use chat or type !command.")
        else
            npcSay("I only take orders from my creator.")
        end
    end)

    npcModel = model
    npcHumanoid = humanoid
    print("[PubAI] NPC spawned")
end

-- ============================================================================
-- CHAT BUBBLE
-- ============================================================================

function npcSay(text)
    if not npcModel or not npcModel:FindFirstChild("Head") then return end

    pcall(function() Chat:Chat(npcModel.Head, text, Enum.ChatColor.Blue) end)

    -- Billboard bubble for longer messages
    local head = npcModel:FindFirstChild("Head")
    if not head then return end

    local old = head:FindFirstChild("ChatBubble")
    if old then old:Destroy() end

    local bubble = Instance.new("BillboardGui")
    bubble.Name = "ChatBubble"
    bubble.Adornee = head
    bubble.Size = UDim2.new(0, 300, 0, 80)
    bubble.StudsOffset = Vector3.new(0, 4, 0)
    bubble.AlwaysOnTop = true
    bubble.Parent = head

    local bg = Instance.new("Frame")
    bg.Size = UDim2.new(1, 0, 1, 0)
    bg.BackgroundColor3 = Color3.fromRGB(15, 20, 35)
    bg.BackgroundTransparency = 0.15
    bg.Parent = bubble
    Instance.new("UICorner", bg).CornerRadius = UDim.new(0, 12)

    local label = Instance.new("TextLabel")
    label.Size = UDim2.new(1, -16, 1, -8)
    label.Position = UDim2.new(0, 8, 0, 4)
    label.BackgroundTransparency = 1
    label.Text = text
    label.TextColor3 = Color3.fromRGB(220, 225, 240)
    label.TextWrapped = true
    label.TextSize = 14
    label.Font = Enum.Font.GothamMedium
    label.TextXAlignment = Enum.TextXAlignment.Left
    label.TextYAlignment = Enum.TextYAlignment.Top
    label.Parent = bg

    Debris:AddItem(bubble, math.max(5, #text * 0.08))
end

-- ============================================================================
-- HTTP TO RELAY SERVER
-- ============================================================================

local function sendCommand(endpoint, payload)
    local ok, result = pcall(function()
        return HttpService:PostAsync(
            CONFIG.BASE_URL .. endpoint,
            HttpService:JSONEncode(payload),
            Enum.HttpContentType.ApplicationJson,
            false
        )
    end)
    if not ok then
        warn("[PubAI] HTTP error:", result)
        return nil
    end
    local decodeOk, decoded = pcall(function() return HttpService:JSONDecode(result) end)
    return decodeOk and decoded or nil
end

-- ============================================================================
-- GAME STATE COLLECTOR
-- ============================================================================

local function getGameState()
    local players = {}
    for _, p in ipairs(Players:GetPlayers()) do
        local char = p.Character
        local pos = char and char:FindFirstChild("HumanoidRootPart") and char.HumanoidRootPart.Position
        table.insert(players, {
            name = p.Name,
            display_name = p.DisplayName,
            position = pos and {x = math.floor(pos.X), y = math.floor(pos.Y), z = math.floor(pos.Z)} or nil,
            health = char and char:FindFirstChild("Humanoid") and char.Humanoid.Health or 0,
        })
    end
    local npcPos = npcModel and npcModel.PrimaryPart and npcModel.PrimaryPart.Position
    return {
        players = players,
        player_count = #players,
        npc_position = npcPos and {x = math.floor(npcPos.X), y = math.floor(npcPos.Y), z = math.floor(npcPos.Z)} or nil,
        place_id = game.PlaceId,
        time_of_day = Lighting.ClockTime,
    }
end

-- ============================================================================
-- PROCESS COMMAND
-- ============================================================================

local function processCommand(player, message)
    if player.Name ~= CONFIG.OWNER then return end

    -- Must be directed at PubAI
    local msg = message:lower()
    local isCommand = msg:find("pubai") or msg:find("pub ai") or msg:find("pub%+%+")
        or msg:sub(1, 1) == "!" or msg:sub(1, 1) == "/"

    if not isCommand then return end

    -- Clean prefix
    local clean = message
        :gsub("[Pp]ub[Aa][Ii]%s*,?%s*", "")
        :gsub("[Pp]ub%s*[Aa][Ii]%s*,?%s*", "")
        :gsub("[Pp]ub%+%+%s*,?%s*", "")
        :gsub("^[!/]%s*", "")

    npcSay("On it...")

    local response = sendCommand("/api/roblox/npc/command", {
        message = clean,
        sender = player.Name,
        game_state = getGameState(),
        conversation_id = conversationId,
    })

    if not response then
        npcSay("Can't reach my server. Is the relay running?")
        return
    end

    conversationId = response.conversation_id or conversationId

    -- Say the response
    if response.response and response.response ~= "" then
        npcSay(response.response)
    end

    -- Execute actions
    if response.actions and type(response.actions) == "table" then
        for _, action in ipairs(response.actions) do
            local ok, err = pcall(function()
                Actions.execute(action, npcModel, npcHumanoid, CONFIG)
            end)
            if not ok then
                warn("[PubAI] Action failed:", action.type, err)
            end
        end
    end
end

-- ============================================================================
-- FOLLOW BEHAVIOR
-- ============================================================================

local function updateFollow()
    if not isFollowing or not followTarget then return end
    local char = followTarget.Character
    if not char or not char:FindFirstChild("HumanoidRootPart") then return end
    if not npcModel or not npcHumanoid then return end

    local targetPos = char.HumanoidRootPart.Position
    local npcPos = npcModel.PrimaryPart.Position
    if (targetPos - npcPos).Magnitude > 8 then
        npcHumanoid:MoveTo(targetPos)
    end
end

-- ============================================================================
-- KEEP NPC ALIVE
-- ============================================================================

local function ensureAlive()
    if not npcModel or not npcModel.Parent or not npcModel:FindFirstChild("Humanoid") then
        createNPC()
    end
    if npcHumanoid then
        npcHumanoid.Health = npcHumanoid.MaxHealth
    end
end

-- ============================================================================
-- GLOBALS FOR ACTION MODULE
-- ============================================================================

_G.PubAI = {
    setFollowing = function(target)
        if target then
            isFollowing = true
            followTarget = target
        else
            isFollowing = false
            followTarget = nil
        end
    end,
    setFlying = function(flying)
        if npcModel and npcModel.PrimaryPart then
            local existing = npcModel.PrimaryPart:FindFirstChild("FlyForce")
            if flying then
                if not existing then
                    local bf = Instance.new("BodyForce")
                    bf.Name = "FlyForce"
                    bf.Force = Vector3.new(0, workspace.Gravity * npcModel.PrimaryPart:GetMass() * 5, 0)
                    bf.Parent = npcModel.PrimaryPart
                end
            else
                if existing then existing:Destroy() end
            end
        end
    end,
    say = npcSay,
    getModel = function() return npcModel end,
}

-- ============================================================================
-- INIT
-- ============================================================================

createNPC()

-- Listen for chat
local function onPlayerAdded(player)
    player.Chatted:Connect(function(message)
        processCommand(player, message)
    end)
    if player.Name == CONFIG.OWNER then
        task.delay(2, function()
            npcSay("Welcome back boss. PubAI online.")
        end)
    end
end

for _, p in ipairs(Players:GetPlayers()) do onPlayerAdded(p) end
Players.PlayerAdded:Connect(onPlayerAdded)

-- Heartbeat: keep alive + follow
RunService.Heartbeat:Connect(function()
    ensureAlive()
    updateFollow()
end)

print("[PubAI] NPC system ready. Owner:", CONFIG.OWNER)
