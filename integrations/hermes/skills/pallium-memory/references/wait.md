# Waiting for Relay replies

When waiting solely for an independent agent's Relay reply, finish useful work that can proceed without it, record the pending reply and next action, then end the turn so idle wake can deliver where qualified. This package does not qualify ordinary-turn fallback or automatic recovery after an uncertain wake; inspect status and trace. Do not keep the turn active by sleeping or polling, or call receive to work around hook delivery. Finish critical operations before yielding.

For an urgent handoff, report the pending state and use an available authorized channel to request an ordinary recipient turn without interrupting existing work. Do not resend. A pending delivery is unconfirmed.
