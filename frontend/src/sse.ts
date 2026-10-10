export interface SseFrame {
  name: string;
  data: string;
}

/** Splits streamed text into complete SSE frames (blank-line delimited); a partial tail is carried to the next push. */
export class SseDecoder {
  private carry = "";

  push(text: string): SseFrame[] {
    this.carry += text.replace(/\r\n?/g, "\n");
    const parts = this.carry.split("\n\n");
    this.carry = parts.pop() ?? "";
    return parts.filter((p) => p.trim()).map((part) => {
      let name = "message";
      let data = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).replace(/^ /, "");
      }
      return { name, data };
    });
  }
}
