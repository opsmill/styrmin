// A URL ends before whitespace or a closing parenthesis; trailing punctuation is text.
const URL_PATTERN = /(https?:\/\/[^\s)]+)/g;
const TRAILING_PUNCTUATION = /[.,;:!?]+$/;

/** Plain text with every http(s) URL rendered as a link that opens in a new tab. */
export function MessageWithLinks({ text }: { text: string }) {
  const parts = text.split(URL_PATTERN);
  return (
    <>
      {parts.map((part, index) => {
        // `split` with a capturing group puts the URLs at odd indexes.
        if (index % 2 === 0) return part;
        const trailing = TRAILING_PUNCTUATION.exec(part)?.[0] ?? "";
        const url = part.slice(0, part.length - trailing.length);
        return (
          <span key={index}>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 break-all"
            >
              {url}
            </a>
            {trailing}
          </span>
        );
      })}
    </>
  );
}
