## Description
Describe the changes introduced by this PR and the reasoning behind them.

## Related Issues
Closes # (issue number)

## Change Type

* [ ] Bug fix
* [ ] Feature
* [ ] Documentation
* [ ] Safety / API boundary
* [ ] Release / packaging
* [ ] GitHub infrastructure

## Risk Level

* [ ] Read-only / docs only
* [ ] Local tooling only
* [ ] FL Studio readback affected
* [ ] FL Studio write path affected
* [ ] Release / package publishing affected

## Evidence

* CI: 
* Local tests: 
* Safety audit: 
* API evidence / probe: 
* Docs build: 

## Checklist
- [ ] My code follows the project's engineering standards (English comments & commits).
- [ ] All safety guidelines in `AGENTS.md` and `docs/ENGINEERING_STANDARDS.md` are satisfied.
- [ ] Offline unit tests pass successfully locally (`pytest`).
- [ ] Safety audit script passes successfully (`python scripts/audit_tool_safety.py --fail-on-gaps`).
- [ ] Anti-vibe check script passes successfully (`python scripts/audit_anti_vibe.py`).
- [ ] I have updated `ROADMAP.md` if any feature status has changed.
