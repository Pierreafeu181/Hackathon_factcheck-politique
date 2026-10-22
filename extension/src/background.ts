// Le clic sur l'icône ouvre le panneau latéral ; le clic droit sur une sélection la fait vérifier ;
// « Vérifier en direct » (clic droit ou Alt+Maj+L) capte le son de l'onglet.

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "verifier", title: "Vérifier cette phrase", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "direct", title: "● Vérifier en direct (son de l'onglet)", contexts: ["page", "frame", "video", "audio", "link"] });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab?.windowId) return;
  if (info.menuItemId === "direct" && tab.id !== undefined) return startLive(tab.id, tab.windowId);
  if (info.menuItemId !== "verifier" || !info.selectionText) return;
  // Ouvrir le panneau avant tout `await` : Chrome exige que ce soit dans le geste de l'utilisateur.
  chrome.sidePanel.open({ windowId: tab.windowId });
  chrome.storage.session.set({
    pendingSelection: { text: info.selectionText, url: tab.url ?? "", title: tab.title ?? "", at: Date.now() },
  });
});

chrome.commands.onCommand.addListener((command, tab) => {
  if (command === "direct" && tab?.id !== undefined && tab.windowId !== undefined) startLive(tab.id, tab.windowId);
});

/**
 * Le clic droit et le raccourci comptent comme une « invocation » de l'extension sur l'onglet :
 * c'est le seul moment où Chrome autorise la capture de son son (tabCapture). On obtient l'identifiant
 * du flux tout de suite, et le panneau s'en sert pour démarrer le direct.
 */
function startLive(tabId: number, windowId: number): void {
  chrome.sidePanel.open({ windowId });
  chrome.tabCapture.getMediaStreamId({ targetTabId: tabId }, (streamId) => {
    const error = chrome.runtime.lastError?.message;
    chrome.storage.session.set({ pendingLive: { tabId, streamId: error ? undefined : streamId, error, at: Date.now() } });
  });
}
