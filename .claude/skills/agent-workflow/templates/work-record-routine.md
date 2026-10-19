<!-- agent-workflow:start -->
<!-- Line-start **Label:** is a field header; unknown/duplicate fields fail.
     Keep prose subheadings outside markers or use plain text. -->
**Outcome:**
<!-- what should be true when complete -->

**Target:**
<!-- affected system, service, or repository -->

**Scope:**
<!-- what may change -->

**Constraints:**
<!-- what must not change or must remain true; "—" if none -->

**Completion criteria:**
<!-- observable outcomes that demonstrate success; one line is fine for routine -->

**Requirement baseline:**
<!-- Before discovery, copy exact Task Context values into this JSON object. Use an authoritative source reference when available. -->
{"source":"work-record-initial","outcome":"...","scope":"...","constraints":"...","completion_criteria":"..."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}
<!-- Copy supplied exact provider/scope_ref/local_ref tuples; [] only for known no-source. -->

**Risk:** Routine
<!-- Routine | Elevated | High. Routine is required for this compact shape; anything else demands the expanded shape. -->

**Complexity:** Simple
<!-- Simple | Moderate | Large. Simple is required for this compact shape; anything else demands the expanded shape. -->

**Reason:**
<!-- Keep this label. Its value is optional for (Routine, Simple): use "—" or leave it empty. Other classifications require the expanded shape and a justification. -->

**Approach:**
<!-- one or two lines on how -->

**Verification:**
<!-- the test(s) and CI job(s) that prove it -->

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready to implement
<!-- agent-workflow:end -->
