--[[
    Pub AI — HTTP API Communication Module
    Handles all HTTP communication with the Pub AI backend.
]]

local HttpService = game:GetService("HttpService")

local API = {}
API.__index = API

function API.new(config)
    local self = setmetatable({}, API)
    self.baseUrl = config.baseUrl or "http://localhost:8000"
    self.apiKey = config.apiKey or ""
    self.conversationId = nil
    self.timeout = 30
    return self
end

function API:setApiKey(key: string)
    self.apiKey = key
end

function API:setBaseUrl(url: string)
    self.baseUrl = url
end

function API:_request(method: string, path: string, body: any?): (boolean, any)
    local url = self.baseUrl .. path
    local headers = {
        ["Content-Type"] = "application/json",
        ["X-API-Key"] = self.apiKey,
    }

    local success, result = pcall(function()
        if method == "GET" then
            return HttpService:GetAsync(url, false, headers)
        else
            local jsonBody = body and HttpService:JSONEncode(body) or ""
            return HttpService:PostAsync(url, jsonBody, Enum.HttpContentType.ApplicationJson, false, headers)
        end
    end)

    if not success then
        return false, { error = tostring(result) }
    end

    local decodeOk, decoded = pcall(function()
        return HttpService:JSONDecode(result)
    end)

    if not decodeOk then
        return true, { raw = result }
    end

    return true, decoded
end

function API:chat(message: string, context: { [string]: any }?): (boolean, any)
    local body = {
        message = message,
        context = context or {
            place_id = game.PlaceId,
            game_name = game:GetService("MarketplaceService"):GetProductInfo(game.PlaceId).Name or "Unknown",
        },
    }
    if self.conversationId then
        body.conversation_id = self.conversationId
    end

    local ok, data = self:_request("POST", "/api/roblox/chat", body)
    if ok and data.conversation_id then
        self.conversationId = data.conversation_id
    end
    return ok, data
end

function API:scan(script: string, scriptName: string?): (boolean, any)
    return self:_request("POST", "/api/roblox/scan", {
        script = script,
        script_name = scriptName or "Unknown",
    })
end

function API:decompile(bytecode: string): (boolean, any)
    return self:_request("POST", "/api/roblox/decompile", {
        bytecode = bytecode,
    })
end

function API:status(): (boolean, any)
    return self:_request("GET", "/api/roblox/status")
end

function API:clearConversation()
    self.conversationId = nil
end

return API
