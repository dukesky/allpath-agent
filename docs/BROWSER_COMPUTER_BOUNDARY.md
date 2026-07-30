# Browser and Computer-Use Boundary

Allpath does not currently expose raw browser or desktop control. This is intentional, not an unfinished hidden feature.

## Browser implementation gate

The first browser release must provide structured navigation, snapshots, stable element references, click/type actions, bounded downloads, domain visibility, and approval before form submission, authentication, purchases, external communication, or destructive actions.

It should run in a dedicated browser profile so Agent cookies and downloads are isolated from the user's primary browser.

## Computer-use implementation gate

Computer use comes after structured browser tools. It must be disabled by default, visibly active, interruptible, and preferably run in an isolated or remote desktop so it does not steal the user's cursor or operate unrelated personal applications.

Allpath will not add a screenshot-and-click loop merely to mark the roadmap complete. The safety boundary and recovery behavior are part of the feature definition.
