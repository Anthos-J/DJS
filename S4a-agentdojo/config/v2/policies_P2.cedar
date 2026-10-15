@id("permit-read")
permit(principal == Agent::"procurement", action == Action::"read", resource);

@id("permit-send")
permit(principal == Agent::"procurement", action == Action::"send", resource);

// G3a confidentiality: approval-gated
@id("g3a")
forbid(principal, action == Action::"send", resource)
  when { context.target.external && context.session.conf > context.target.clearance && !context.approved };

// G3b integrity-conditioned egress: approval-gated
@id("g3b")
forbid(principal, action == Action::"send", resource)
  when { context.target.external && context.session.integ == 0
         && context.session.conf >= context.target.untrusted_threshold && !context.approved };

// G2 grounding: approval-gated
@id("g2")
forbid(principal, action == Action::"send", resource)
  when { !context.params.all_grounded && !context.approved };

// hard ceiling: no approval can lift
@id("hard-hr")
forbid(principal, action, resource == Resource::"hr_records");

// ---- CANDIDATE v2 additions (Wave 6; P above is unchanged) ----
// G2b provenance-after-taint: once the session has read untrusted content (integ == 0), every effect's
// consequential arguments must come from the user's own request, not from data the agent has read. Approval-gated.
@id("g2b")
forbid(principal, action == Action::"send", resource)
  when { context.session.integ == 0 && !context.params.prompt_grounded && !context.approved };
