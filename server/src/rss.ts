import { XMLParser } from "fast-xml-parser";

export interface Feed {
  id: string;
  name: string;
  kind: "podcast" | "youtube";
  url: string;
}

export interface FeedItem {
  id: string;
  title: string;
  url: string;
  audioUrl?: string;
  publishedAt: string;
}

const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: "@" });

const asArray = <T>(x: T | T[] | undefined): T[] => (x === undefined ? [] : Array.isArray(x) ? x : [x]);
const text = (x: unknown): string => (typeof x === "object" && x !== null ? String((x as any)["#text"] ?? "") : String(x ?? "")).trim();

/** Lit un flux RSS 2.0 (podcast) ou Atom (YouTube) et renvoie les épisodes, du plus récent au plus ancien. */
export function parseFeed(xml: string, feed: Feed): FeedItem[] {
  const doc = parser.parse(xml);
  const items: FeedItem[] = doc.feed ? parseAtom(doc.feed, feed) : parseRss(doc.rss?.channel, feed);
  return items.sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
}

function parseRss(channel: any, feed: Feed): FeedItem[] {
  return asArray(channel?.item).flatMap((item: any) => {
    const audioUrl = asArray(item.enclosure).map((e: any) => e["@url"]).find(Boolean);
    if (!audioUrl) return [];
    const guid = text(item.guid) || audioUrl;
    return [{
      id: `${feed.id}:${guid}`,
      title: text(item.title),
      url: text(item.link) || audioUrl,
      audioUrl,
      publishedAt: new Date(text(item.pubDate)).toISOString(),
    }];
  });
}

function parseAtom(atom: any, feed: Feed): FeedItem[] {
  return asArray(atom.entry).map((entry: any) => {
    const videoId = text(entry["yt:videoId"]);
    return {
      id: `${feed.id}:${videoId}`,
      title: text(entry.title),
      url: `https://www.youtube.com/watch?v=${videoId}`,
      publishedAt: new Date(text(entry.published)).toISOString(),
    };
  });
}

export async function fetchFeed(feed: Feed): Promise<FeedItem[]> {
  const res = await fetch(feed.url, { headers: { "User-Agent": "Mozilla/5.0 (verifpol)" } });
  if (!res.ok) throw new Error(`Flux ${feed.name} : HTTP ${res.status}`);
  return parseFeed(await res.text(), feed);
}
