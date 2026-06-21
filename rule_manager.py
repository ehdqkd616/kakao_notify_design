import re
from config import ConfigManager


class RuleManager:
    def __init__(self, config: ConfigManager):
        self.config = config

    def match(self, chat_name: str) -> str | None:
        rules = self.config.rules

        # 1단계: Exact match
        for rule in rules:
            if rule.get("type") == "exact" and rule.get("keyword") == chat_name:
                return None if rule.get("mute") else rule.get("sound", "")

        # 2단계: Contains match
        for rule in rules:
            if rule.get("type") == "contains" and rule.get("keyword", "") in chat_name:
                return None if rule.get("mute") else rule.get("sound", "")

        # 3단계: Regex match
        for rule in rules:
            if rule.get("type") == "regex":
                try:
                    if re.search(rule.get("keyword", ""), chat_name):
                        return None if rule.get("mute") else rule.get("sound", "")
                except re.error:
                    pass

        # 4단계: Default
        return self.config.default_sound

    def add_rule(self, rule: dict) -> None:
        rules = list(self.config.rules)
        if "id" not in rule:
            existing_ids = {r.get("id", "") for r in rules}
            idx = len(rules) + 1
            while f"rule_{idx:03d}" in existing_ids:
                idx += 1
            rule["id"] = f"rule_{idx:03d}"
        rules.append(rule)
        self.config.rules = rules
        self.config.save()

    def remove_rule(self, rule_id: str) -> None:
        self.config.rules = [r for r in self.config.rules if r.get("id") != rule_id]
        self.config.save()

    def update_rule(self, rule_id: str, updated: dict) -> None:
        rules = list(self.config.rules)
        for i, rule in enumerate(rules):
            if rule.get("id") == rule_id:
                rules[i] = {**rule, **updated}
                break
        self.config.rules = rules
        self.config.save()
