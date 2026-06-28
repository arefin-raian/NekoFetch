import asyncio
from nekofetch.sources.telegram.anilist import AnilistClient, _GRAPH_QUERY, _TRAVERSE_RELATIONS, _ANIME_FORMATS

async def main():
    cli = AnilistClient()
    m = await cli.search("Attack on Titan")
    root = m.id
    # BFS print the graph with edge types so we can see what's a season vs spinoff
    visited={root}; frontier=[root]; seen_nodes={}
    edges=[]
    while frontier:
        batch=frontier[:50]; frontier=frontier[50:]
        data=await cli._post(_GRAPH_QUERY, {"ids":batch})
        for md in (data or {}).get("Page",{}).get("media",[]):
            seen_nodes[md["id"]]=(md.get("format"), md.get("episodes"))
            for e in md.get("relations",{}).get("edges",[]):
                rt=e.get("relationType"); node=e.get("node") or {}
                if node.get("type")=="ANIME" and node.get("format") in _ANIME_FORMATS and rt in _TRAVERSE_RELATIONS:
                    edges.append((md["id"], rt, node["id"], node.get("format")))
                    if node["id"] not in visited:
                        visited.add(node["id"]); frontier.append(node["id"])
    # fetch titles for TV nodes
    tv = [nid for nid,(f,e) in seen_nodes.items() if f in ("TV","TV_SHORT")]
    print("root:", root, "TV nodes:", len(tv))
    # print edges among TV nodes
    for a,rt,b,bf in edges:
        if seen_nodes.get(a,(None,))[0] in ("TV","TV_SHORT") or bf in ("TV","TV_SHORT"):
            print(f"  {a} -{rt}-> {b} ({bf})")
    await cli.close()
asyncio.run(main())
