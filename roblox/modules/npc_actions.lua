--[[
    PubAI NPC Actions — ModuleScript
    Place in ServerScriptService (same level as PubAI_NPC)

    Executes action payloads returned by the relay server.
]]

local Players = game:GetService("Players")
local Lighting = game:GetService("Lighting")
local Debris = game:GetService("Debris")
local TweenService = game:GetService("TweenService")

local Actions = {}

-- ============================================================================
-- HELPERS
-- ============================================================================

local function toVector3(t)
    if type(t) == "table" then return Vector3.new(t[1] or 0, t[2] or 0, t[3] or 0) end
    return Vector3.new(0, 0, 0)
end

local function toColor3(t)
    if type(t) == "table" then return Color3.fromRGB(t[1] or 255, t[2] or 255, t[3] or 255) end
    return Color3.fromRGB(255, 255, 255)
end

local function findObject(path)
    if not path or path == "" then return nil end
    -- Wildcard search by name
    if path:sub(1, 1) == "*" then
        local name = path:sub(2)
        local function search(parent)
            for _, child in ipairs(parent:GetChildren()) do
                if child.Name == name then return child end
                local found = search(child)
                if found then return found end
            end
            return nil
        end
        return search(workspace)
    end
    -- Dot-path traversal
    local current = game
    for segment in path:gmatch("[^%.]+") do
        current = current:FindFirstChild(segment)
        if not current then return nil end
    end
    return current
end

local function findPlayer(name)
    for _, p in ipairs(Players:GetPlayers()) do
        if p.Name == name or p.DisplayName == name then return p end
    end
    return nil
end

local function getMaterial(str)
    local materials = {
        SmoothPlastic = Enum.Material.SmoothPlastic,
        Neon = Enum.Material.Neon,
        Glass = Enum.Material.Glass,
        Wood = Enum.Material.Wood,
        Metal = Enum.Material.Metal,
        Grass = Enum.Material.Grass,
        Brick = Enum.Material.Brick,
        Concrete = Enum.Material.Concrete,
        Marble = Enum.Material.Marble,
        Granite = Enum.Material.Granite,
        Sand = Enum.Material.Sand,
        Ice = Enum.Material.Ice,
        DiamondPlate = Enum.Material.DiamondPlate,
        Foil = Enum.Material.Foil,
        Plastic = Enum.Material.Plastic,
    }
    return materials[str] or Enum.Material.SmoothPlastic
end

-- ============================================================================
-- ACTION HANDLERS
-- ============================================================================

local handlers = {}

handlers.create_part = function(params)
    local part = Instance.new("Part")
    part.Name = params.name or "PubAI_Part"
    part.Anchored = params.anchored ~= false
    part.Size = params.size and toVector3(params.size) or Vector3.new(4, 4, 4)
    part.Position = params.position and toVector3(params.position) or Vector3.new(0, 10, 0)
    part.Color = params.color and toColor3(params.color) or Color3.fromRGB(0, 170, 255)
    part.Material = params.material and getMaterial(params.material) or Enum.Material.SmoothPlastic

    local shape = params.shape and params.shape:lower() or "block"
    if shape == "ball" or shape == "sphere" then
        part.Shape = Enum.PartType.Ball
    elseif shape == "cylinder" then
        part.Shape = Enum.PartType.Cylinder
    elseif shape == "wedge" then
        part:Destroy()
        part = Instance.new("WedgePart")
        part.Name = params.name or "PubAI_Part"
        part.Anchored = params.anchored ~= false
        part.Size = params.size and toVector3(params.size) or Vector3.new(4, 4, 4)
        part.Position = params.position and toVector3(params.position) or Vector3.new(0, 10, 0)
        part.Color = params.color and toColor3(params.color) or Color3.fromRGB(0, 170, 255)
        part.Material = params.material and getMaterial(params.material) or Enum.Material.SmoothPlastic
    end

    if params.transparency then part.Transparency = params.transparency end
    if params.reflectance then part.Reflectance = params.reflectance end
    if params.cancollide ~= nil then part.CanCollide = params.cancollide end

    part.Parent = workspace
    return part
end

handlers.destroy = function(params)
    local obj = findObject(params.target)
    if obj and obj ~= workspace and obj ~= game then
        obj:Destroy()
    end
end

handlers.teleport_player = function(params)
    local player = findPlayer(params.player)
    if player and player.Character and player.Character:FindFirstChild("HumanoidRootPart") then
        player.Character.HumanoidRootPart.CFrame = CFrame.new(toVector3(params.position))
    end
end

handlers.teleport_npc = function(params, npcModel)
    if npcModel and npcModel.PrimaryPart then
        npcModel:SetPrimaryPartCFrame(CFrame.new(toVector3(params.position)))
    end
end

handlers.npc_follow = function(params)
    if _G.PubAI then
        if params.stop then
            _G.PubAI.setFollowing(nil)
        elseif params.player then
            local player = findPlayer(params.player)
            if player then _G.PubAI.setFollowing(player) end
        end
    end
end

handlers.npc_fly = function(params)
    if _G.PubAI then
        _G.PubAI.setFlying(params.enabled == true)
    end
end

handlers.create_script = function(params)
    local scriptType = params.script_type or "Script"
    local obj
    if scriptType == "LocalScript" then
        obj = Instance.new("LocalScript")
    elseif scriptType == "ModuleScript" then
        obj = Instance.new("ModuleScript")
    else
        obj = Instance.new("Script")
    end
    obj.Name = params.name or "PubAI_Script"
    obj.Source = params.source or "-- PubAI generated script"

    local parent = findObject(params.parent) or workspace
    obj.Parent = parent
end

handlers.modify = function(params)
    local obj = findObject(params.target)
    if not obj then return end
    local props = params.properties or {}
    for prop, val in pairs(props) do
        pcall(function()
            if prop == "Color" and type(val) == "table" then
                obj[prop] = toColor3(val)
            elseif prop == "Size" and type(val) == "table" then
                obj[prop] = toVector3(val)
            elseif prop == "Position" and type(val) == "table" then
                obj[prop] = toVector3(val)
            elseif prop == "CFrame" and type(val) == "table" then
                obj[prop] = CFrame.new(toVector3(val))
            elseif prop == "Material" and type(val) == "string" then
                obj[prop] = getMaterial(val)
            else
                obj[prop] = val
            end
        end)
    end
end

handlers.clone = function(params)
    local obj = findObject(params.target)
    if obj then
        local cloned = obj:Clone()
        if params.position and cloned:IsA("BasePart") then
            cloned.Position = toVector3(params.position)
        elseif params.position and cloned:IsA("Model") and cloned.PrimaryPart then
            cloned:SetPrimaryPartCFrame(CFrame.new(toVector3(params.position)))
        end
        cloned.Parent = obj.Parent
    end
end

handlers.effect = function(params)
    local effectType = params.type or "Explosion"
    local pos = params.position and toVector3(params.position) or Vector3.new(0, 10, 0)

    if effectType == "Explosion" then
        local exp = Instance.new("Explosion")
        exp.Position = pos
        exp.BlastRadius = params.params and params.params.radius or 20
        exp.BlastPressure = params.params and params.params.pressure or 0
        exp.DestroyJointRadiusPercent = params.params and params.params.destroy and 1 or 0
        exp.Parent = workspace
    else
        local anchor = Instance.new("Part")
        anchor.Name = "PubAI_Effect"
        anchor.Anchored = true
        anchor.Transparency = 1
        anchor.CanCollide = false
        anchor.Size = Vector3.new(1, 1, 1)
        anchor.Position = pos
        anchor.Parent = workspace

        local emitter
        if effectType == "Fire" then
            emitter = Instance.new("Fire")
            if params.params and params.params.size then emitter.Size = params.params.size end
        elseif effectType == "Smoke" then
            emitter = Instance.new("Smoke")
        elseif effectType == "Sparkles" then
            emitter = Instance.new("Sparkles")
        elseif effectType == "ParticleEmitter" then
            emitter = Instance.new("ParticleEmitter")
            if params.params and params.params.color then
                emitter.Color = ColorSequence.new(toColor3(params.params.color))
            end
            emitter.Rate = params.params and params.params.rate or 50
        end
        if emitter then emitter.Parent = anchor end

        local duration = params.params and params.params.duration or 10
        Debris:AddItem(anchor, duration)
    end
end

handlers.sound = function(params)
    local sound = Instance.new("Sound")
    sound.SoundId = params.id or ""
    sound.Volume = params.volume or 1

    if params.global then
        sound.Parent = workspace
    else
        local anchor = Instance.new("Part")
        anchor.Anchored = true
        anchor.Transparency = 1
        anchor.CanCollide = false
        anchor.Size = Vector3.new(1, 1, 1)
        anchor.Position = params.position and toVector3(params.position) or Vector3.new(0, 10, 0)
        anchor.Parent = workspace
        sound.Parent = anchor
        Debris:AddItem(anchor, 30)
    end

    sound:Play()
    Debris:AddItem(sound, 30)
end

handlers.message = function(params)
    local msgType = params.type or "Hint"
    local text = params.text or ""
    local duration = params.duration or 5

    if msgType == "Hint" then
        local hint = Instance.new("Hint")
        hint.Text = text
        hint.Parent = workspace
        Debris:AddItem(hint, duration)
    elseif msgType == "Message" then
        local msg = Instance.new("Message")
        msg.Text = text
        msg.Parent = workspace
        Debris:AddItem(msg, duration)
    end
end

handlers.lighting = function(params)
    for prop, val in pairs(params) do
        pcall(function()
            if prop == "Ambient" and type(val) == "table" then
                Lighting[prop] = toColor3(val)
            elseif prop == "OutdoorAmbient" and type(val) == "table" then
                Lighting[prop] = toColor3(val)
            elseif prop == "ColorShift_Top" and type(val) == "table" then
                Lighting[prop] = toColor3(val)
            else
                Lighting[prop] = val
            end
        end)
    end
end

handlers.speed = function(params)
    local player = findPlayer(params.player)
    if player and player.Character and player.Character:FindFirstChild("Humanoid") then
        local hum = player.Character.Humanoid
        if params.walkspeed then hum.WalkSpeed = params.walkspeed end
        if params.jumppower then hum.JumpPower = params.jumppower end
    end
end

handlers.forcefield = function(params)
    local player = findPlayer(params.player)
    if player and player.Character then
        if params.enabled then
            local ff = Instance.new("ForceField")
            ff.Name = "PubAI_FF"
            ff.Parent = player.Character
            if params.duration then
                Debris:AddItem(ff, params.duration)
            end
        else
            local ff = player.Character:FindFirstChild("PubAI_FF")
            if ff then ff:Destroy() end
        end
    end
end

handlers.damage = function(params)
    local player = findPlayer(params.player)
    if player and player.Character and player.Character:FindFirstChild("Humanoid") then
        player.Character.Humanoid:TakeDamage(params.amount or 10)
    end
end

handlers.heal = function(params)
    local player = findPlayer(params.player)
    if player and player.Character and player.Character:FindFirstChild("Humanoid") then
        local hum = player.Character.Humanoid
        hum.Health = math.min(hum.Health + (params.amount or 50), hum.MaxHealth)
    end
end

handlers.kick = function(params)
    local player = findPlayer(params.player)
    if player then
        player:Kick(params.reason or "Kicked by PubAI")
    end
end

handlers.give_tool = function(params)
    local player = findPlayer(params.player)
    if player then
        local tool = Instance.new("Tool")
        tool.Name = params.tool_name or "PubAI_Tool"
        tool.RequiresHandle = true
        local handle = Instance.new("Part")
        handle.Name = "Handle"
        handle.Size = Vector3.new(1, 1, 4)
        handle.Color = Color3.fromRGB(0, 170, 255)
        handle.Parent = tool

        if params.tool_source then
            local s = Instance.new("Script")
            s.Source = params.tool_source
            s.Parent = tool
        end

        local bp = player:FindFirstChild("Backpack")
        if bp then tool.Parent = bp end
    end
end

handlers.clear_workspace = function()
    for _, child in ipairs(workspace:GetChildren()) do
        if child:IsA("BasePart") and child.Name ~= "Baseplate" and child.Name ~= "Terrain" then
            if not child:FindFirstChildOfClass("Humanoid") then
                child:Destroy()
            end
        elseif child:IsA("Model") and not child:FindFirstChildOfClass("Humanoid") then
            if child.Name ~= "Camera" then
                child:Destroy()
            end
        end
    end
end

handlers.build_structure = function(params)
    local pos = params.position and toVector3(params.position) or Vector3.new(0, 0, 0)
    local color = params.color and toColor3(params.color) or Color3.fromRGB(120, 120, 120)
    local mat = params.material and getMaterial(params.material) or Enum.Material.SmoothPlastic
    local sizeScale = (params.size == "large" and 2) or (params.size == "small" and 0.5) or 1
    local structType = params.type or "platform"

    local folder = Instance.new("Folder")
    folder.Name = "PubAI_" .. structType
    folder.Parent = workspace

    local function makePart(name, size, position)
        local p = Instance.new("Part")
        p.Name = name
        p.Anchored = true
        p.Size = size * sizeScale
        p.Position = pos + position * sizeScale
        p.Color = color
        p.Material = mat
        p.Parent = folder
        return p
    end

    if structType == "platform" then
        makePart("Floor", Vector3.new(20, 1, 20), Vector3.new(0, 0, 0))

    elseif structType == "wall" then
        makePart("Wall", Vector3.new(20, 10, 1), Vector3.new(0, 5, 0))

    elseif structType == "tower" then
        makePart("Base", Vector3.new(8, 1, 8), Vector3.new(0, 0, 0))
        makePart("Pillar", Vector3.new(6, 30, 6), Vector3.new(0, 15.5, 0))
        makePart("Top", Vector3.new(10, 1, 10), Vector3.new(0, 31, 0))

    elseif structType == "house" then
        -- Floor
        makePart("Floor", Vector3.new(20, 1, 20), Vector3.new(0, 0, 0))
        -- Walls
        makePart("WallFront", Vector3.new(20, 10, 1), Vector3.new(0, 5.5, -9.5))
        makePart("WallBack", Vector3.new(20, 10, 1), Vector3.new(0, 5.5, 9.5))
        makePart("WallLeft", Vector3.new(1, 10, 20), Vector3.new(-9.5, 5.5, 0))
        makePart("WallRight", Vector3.new(1, 10, 20), Vector3.new(9.5, 5.5, 0))
        -- Roof
        makePart("Roof", Vector3.new(22, 1, 22), Vector3.new(0, 11, 0))
        -- Door hole (just make front wall shorter and add gap)

    elseif structType == "staircase" then
        for i = 0, 9 do
            makePart("Step" .. i, Vector3.new(6, 1, 3), Vector3.new(0, i * 1, i * 3))
        end
    end
end

-- ============================================================================
-- MAIN EXECUTOR
-- ============================================================================

function Actions.execute(action, npcModel, npcHumanoid, config)
    local actionType = action.type
    local params = action.params or action

    local handler = handlers[actionType]
    if handler then
        if actionType == "teleport_npc" then
            handler(params, npcModel)
        else
            handler(params)
        end
    else
        warn("[PubAI] Unknown action:", actionType)
    end
end

return Actions
