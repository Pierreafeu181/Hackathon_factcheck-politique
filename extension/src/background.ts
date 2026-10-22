// Le clic sur l'icône ouvre le panneau latéral ; le clic droit sur une sélection la fait vérifier.

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "verifier", title: "Vérifier cette phrase", contexts: ["selection"] });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== "verifier" || !tab?.windowId || !info.selectionText) return;
  // Ouvrir le panneau avant tout `await` : Chrome exige que ce soit dans le geste de l'utilisateur.
  chrome.sidePanel.open({ windowId: tab.windowId });
  chrome.storage.session.set({
    pendingSelection: { text: info.selectionText, url: tab.url ?? "", title: tab.title ?? "", at: Date.now() },
  });
});
