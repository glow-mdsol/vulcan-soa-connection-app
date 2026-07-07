import { useSearchParams } from "react-router-dom";

const REASON_MESSAGES: Record<string, string> = {
  untrusted_iss: "This app was launched from an unrecognized FHIR server.",
  invalid_state: "Your sign-in session expired or was already used.",
};

export default function LaunchError() {
  const [searchParams] = useSearchParams();
  const reason = searchParams.get("reason");
  const message = (reason && REASON_MESSAGES[reason]) ?? "Sign-in failed.";

  return (
    <div className="status-card">
      <p role="alert" className="alert">
        {message}
      </p>
      <p>Please relaunch this app from your EHR.</p>
    </div>
  );
}
