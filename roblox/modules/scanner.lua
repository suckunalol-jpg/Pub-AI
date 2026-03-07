--[[
    Pub AI — Script Scanner Module
    Scans workspace and game hierarchy for scripts, analyzes them via the AI backend.
]]

local Scanner = {}
Scanner.__index = Scanner

function Scanner.new(apiModule)
    local self = setmetatable({}, Scanner)
    self.api = apiModule
    self.results = {}
    return self
end

function Scanner:getScripts(root: Instance?): { { instance: Instance, source: string, name: string } }
    root = root or game:GetService("Workspace")
    local scripts = {}

    local function recurse(parent)
        for _, child in ipairs(parent:GetChildren()) do
            if child:IsA("ModuleScript") or child:IsA("LocalScript") or child:IsA("Script") then
                local ok, source = pcall(function()
                    return child.Source
                end)
                table.insert(scripts, {
                    instance = child,
                    source = (ok and source) or "",
                    name = child:GetFullName(),
                    className = child.ClassName,
                })
            end
            pcall(function() recurse(child) end)
        end
    end

    pcall(function() recurse(root) end)
    return scripts
end

function Scanner:scanScript(scriptInfo: { source: string, name: string }): (boolean, any)
    return self.api:scan(scriptInfo.source, scriptInfo.name)
end

function Scanner:scanAll(root: Instance?, onProgress: ((number, number, string) -> ())?): { any }
    local scripts = self:getScripts(root)
    local results = {}

    for i, info in ipairs(scripts) do
        if onProgress then
            onProgress(i, #scripts, info.name)
        end

        local ok, analysis = self:scanScript(info)
        table.insert(results, {
            name = info.name,
            success = ok,
            analysis = ok and analysis or { error = "Scan failed" },
        })

        -- Small yield to prevent timeout
        if i % 3 == 0 then
            task.wait(0.1)
        end
    end

    self.results = results
    return results
end

function Scanner:getScriptCount(root: Instance?): number
    return #self:getScripts(root)
end

return Scanner
