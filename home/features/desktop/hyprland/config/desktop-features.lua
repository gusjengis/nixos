-- Home Manager materializes these module choices for this installation.
-- Existing desktops keep their behavior until their next activation.
local ok, features = pcall(require, "host-features")
return ok and features or { contexts = true, personal = true, development = true }
