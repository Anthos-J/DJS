@id("Q_G3a")
permit(principal, action, resource)
  unless { action == Action::"send" && context.target.external
           && context.session.conf > context.target.clearance && !context.approved };
