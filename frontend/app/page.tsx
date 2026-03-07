"use client";

import { useState } from "react";
import BinaryRain from "@/components/BinaryRain";
import Sidebar from "@/components/Sidebar";
import ChatInterface from "@/components/ChatInterface";
import AgentPanel from "@/components/AgentPanel";
import WorkflowBuilder from "@/components/WorkflowBuilder";
import KnowledgeUpload from "@/components/KnowledgeUpload";
import TrainingPanel from "@/components/TrainingPanel";
import ApiKeyPanel from "@/components/ApiKeyPanel";

export type ActiveView = "chat" | "agents" | "workflows" | "knowledge" | "training" | "roblox";

export default function Home() {
  const [activeView, setActiveView] = useState<ActiveView>("chat");

  const renderView = () => {
    switch (activeView) {
      case "chat":
        return <ChatInterface />;
      case "agents":
        return <AgentPanel />;
      case "workflows":
        return <WorkflowBuilder />;
      case "knowledge":
        return <KnowledgeUpload />;
      case "training":
        return <TrainingPanel />;
      case "roblox":
        return <ApiKeyPanel />;
    }
  };

  return (
    <main className="relative h-screen w-screen overflow-hidden">
      <BinaryRain />
      <div className="relative z-10 flex h-full">
        <Sidebar activeView={activeView} onViewChange={setActiveView} />
        <div className="flex-1 flex flex-col overflow-hidden">
          {renderView()}
        </div>
      </div>
    </main>
  );
}
