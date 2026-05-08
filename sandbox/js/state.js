export function createPaneState(initialPrompt) {
  const subscribers = new Set();
  const notify = () => { for (const fn of subscribers) fn(); };

  return {
    systemPrompt: initialPrompt,
    messages: [{ role: "system", content: initialPrompt }],

    reset() {
      this.messages = [{ role: "system", content: this.systemPrompt }];
      notify();
    },
    applyPrompt(newPrompt) {
      this.systemPrompt = newPrompt;
      this.messages = [{ role: "system", content: newPrompt }];
      notify();
    },
    addUser(text) {
      this.messages.push({ role: "user", content: text });
      notify();
    },
    addAssistant(text) {
      this.messages.push({ role: "assistant", content: text });
      notify();
    },
    popLastUser() {
      const last = this.messages[this.messages.length - 1];
      if (!last || last.role !== "user") return false;
      this.messages.pop();
      notify();
      return true;
    },
    loadSnapshot({ systemPrompt, messages }) {
      this.systemPrompt = systemPrompt;
      this.messages = [...messages];
      notify();
    },
    buildTurnMessages(vaultMessage) {
      let sys = this.systemPrompt;
      const allMsgs = [...this.messages];
      const lastUser = [...allMsgs].reverse().find(m => m.role === "user");

      let filteredMsgs = allMsgs;
      if (sys.includes("{{user inserts directive here}}") && lastUser) {
        sys = sys.replace("{{user inserts directive here}}", lastUser.content);
        // Replace the injected user message with a simple trigger
        const lastIdx = allMsgs.lastIndexOf(lastUser);
        filteredMsgs = allMsgs.map((m, i) => 
          i === lastIdx ? { ...m, content: "Proceed with the directive above." } : m
        );
      }

      const msgs = [{ role: "system", content: sys }, ...filteredMsgs.slice(1)];
      if (!vaultMessage) return msgs;
      return [msgs[0], vaultMessage, ...msgs.slice(1)];
    },
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };
}
