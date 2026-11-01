// Chat thread between the candidate and the scheduling assistant; keeps the newest message in view
import { useEffect, useRef } from "react";

export function ChatThread({ history, sending }) {
  const end = useRef(null);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [history.length, sending]);

  return (
    <div className="thread" aria-live="polite">
      {history.length === 0 && !sending && (
        <p className="thread-hint">Tell me when you're free, or just ask which times are available.</p>
      )}
      {history.map((message, i) => (
        <p key={`${message.at}-${i}`} className={`msg msg-${message.role}`}>{message.text}</p>
      ))}
      {sending && (
        <>
          <p className="msg msg-candidate">{sending}</p>
          <p className="msg msg-agent msg-typing" aria-label="The assistant is typing">
            <span /><span /><span />
          </p>
        </>
      )}
      <div ref={end} />
    </div>
  );
}
