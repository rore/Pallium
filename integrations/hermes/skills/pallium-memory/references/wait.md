# Waiting for Relay replies

When waiting solely for an independent agent's Relay reply, finish useful work that can proceed without it, record the pending reply and next action, then end the turn so idle wake can deliver where supported. Where wake is unavailable, continue on the next ordinary turn. Do not keep the turn active by sleeping or polling, or call receive to work around hook delivery. Finish critical operations before yielding.

For an urgent handoff, open the recipient task, let its current work finish, and start an ordinary turn if needed; do not resend. A pending delivery is unconfirmed.
