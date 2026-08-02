# Browser and Computer-Use Boundary

Allpath ships a structured, approval-gated browser (see [Browser](BROWSER.md)): isolated profile, public-network URL enforcement, bounded snapshots with stable element references, and controlled screenshots and downloads. Raw pixel-level browser control and desktop computer use remain intentionally unexposed.

## Browser implementation gate

The shipped browser satisfies this gate: structured navigation, snapshots, stable element references, approval-gated click/type actions, bounded downloads and screenshots in private fixed directories, and repeated public-URL validation on navigation, redirects, and subresource requests. Form submission, authentication, purchases, external communication, and destructive actions remain approval-gated through the standard side-effect boundary.

## Computer-use implementation gate

Computer use comes after structured browser tools. It must be disabled by default, visibly active, interruptible, and preferably run in an isolated or remote desktop so it does not steal the user's cursor or operate unrelated personal applications.

Allpath will not add a screenshot-and-click loop merely to mark the roadmap complete. The safety boundary and recovery behavior are part of the feature definition.
