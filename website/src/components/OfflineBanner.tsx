import React from "react";

interface OfflineBannerProps {
  message?: string;
  onDismiss: () => void;
}

/**
 * Dismissible banner shown when the local runtime API (or a legacy
 * backend endpoint) is unreachable. Lets legacy views render a clean
 * placeholder instead of an infinite spinner or a crashed view.
 */
const OfflineBanner: React.FC<OfflineBannerProps> = ({
  message = "Not available in local mode: the backend endpoint for this view is unreachable.",
  onDismiss,
}) => (
  <div className="alert alert-warning alert-dismissible fade show" role="alert">
    {message}
    <button
      type="button"
      className="btn-close"
      aria-label="Close"
      onClick={onDismiss}
    />
  </div>
);

export default OfflineBanner;
