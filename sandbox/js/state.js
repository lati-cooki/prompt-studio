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
      if (!vaultMessage) return [...this.messages];
      return [this.messages[0], vaultMessage, ...this.messages.slice(1)];
    },
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };
}
