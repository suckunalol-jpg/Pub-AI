import os
import logging
from agent_engine.tools_base import BaseTool, register_tool

logger = logging.getLogger(__name__)

@register_tool
class SkillsTool(BaseTool):
    """Access dynamic skills from SKILL.md files."""
    name = "skills_tool"
    description = (
        "Discover and load specialized skills. "
        "Args: action (list | load), skill_name (optional, name of skill to load). "
        "Returns the list of skills or the skill instructions."
    )

    async def execute(self) -> str:
        action = self.args.get("action", "list")
        skill_name = self.args.get("skill_name", "")
        
        # Determine skills directory relative to project root / backend
        skills_dir = os.path.join(os.getcwd(), "skills")
        
        if not os.path.exists(skills_dir):
            os.makedirs(skills_dir, exist_ok=True)
            return "No skills found. Skills directory created."
            
        if action == "list":
            skills = []
            for item in os.listdir(skills_dir):
                if os.path.isdir(os.path.join(skills_dir, item)):
                    if os.path.exists(os.path.join(skills_dir, item, "SKILL.md")):
                        skills.append(item)
            if not skills:
                return "No skills available."
            return f"Available skills: {', '.join(skills)}\n\nUse action='load' with skill_name to read a skill's instructions."
            
        elif action == "load":
            if not skill_name:
                return "Error: skill_name required for load action."
            skill_path = os.path.join(skills_dir, skill_name, "SKILL.md")
            if not os.path.exists(skill_path):
                return f"Error: Skill '{skill_name}' not found."
            with open(skill_path, "r", encoding="utf-8") as f:
                return f.read()
                
        return "Error: Unknown action."
