# Vision and principles

## The direction

Mycelium should feel like a hopeful, active workshop for a real homelab: the person can see which devices and agents are present, what they are doing, what is waiting, and why. A digital resident should have a useful role grounded in real services or hardware, not pretend activity.

The long-term picture includes local-first agents that can hand bounded work to other agents, live presence across devices, deliberate remote access, local camera understanding, and carefully gated physical workflows such as print queues. These are goals, not claims about the current build.

## Design values

1. **Truthful presence.** “Working” means a real task or observable activity exists. Unavailable means unavailable.
2. **Local by default.** Local Hermes and Ollama are preferred. Online models are an explicit model/provider choice.
3. **People keep agency.** Proposals are reviewable; sensitive, physical, and desktop-input actions remain gated.
4. **Small capabilities.** A node offers specific capabilities; no wildcard or general shell execution.
5. **Recoverable data.** Backups before sync, migration, or destructive actions.
6. **Connected, not entangled.** Services can cooperate over APIs without merging databases or creating ambiguous ownership.
7. **Useful calm.** The interface should make the next action clear, show live signals, and avoid decorative activity that looks real but is not.

## Ethical operating line

- Do not enable camera, microphone, desktop input, fabrication, or other hardware actions without clear user intent and a visible status.
- Make node capabilities visible and revocable.
- Keep the default node pull-only and never imply that the coordinator can reach into a machine.
- Local model use does not automatically make every data flow safe; show where prompts and files go.
- Keep a human review step for external sharing, irreversible changes, and real-world actuation.
