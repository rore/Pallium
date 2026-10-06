# Waiting for Relay replies

When waiting solely for independent agents' Relay replies, finish useful work that can proceed without them, record pending replies and the next action, then end the turn so idle wake can deliver. Do not keep the turn active solely by sleeping or polling for replies, or call receive to work around hook delivery. Finish critical operations before yielding; normal tool and native-subagent waits remain valid. This guidance does not replace reliable delivery once idle.

For an urgent handoff, open the recipient task, let its current work finish, and start an ordinary turn if needed; do not resend. A pending delivery is unconfirmed.
