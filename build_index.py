"""Construit l'index compact du shop dope.gallery pour le filtre rapide.

Lit les pages publiques /shop?format=json (les mêmes données que le filtre actuel
télécharge à chaque visite) et écrit un seul fichier JSON léger : uniquement ce
qu'il faut pour filtrer et afficher les cartes. Aucune donnée privée : tout ce qui
est dans ce fichier est déjà visible par n'importe quel visiteur du site.

Usage : python build_index.py [-o shop-index.json]
"""
import argparse, gzip, json, sys, time, urllib.request

BASE = "https://dope.gallery"
UA = "Mozilla/5.0 (dope-index-builder)"
IMG_PREFIX = "https://images.squarespace-cdn.com/"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except Exception as e:  # réseau capricieux : on réessaie
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def fetch_all():
    url, pages, items, cats = "/shop?format=json", 0, [], None
    while url:
        if "format=json" not in url:
            url += ("&" if "?" in url else "?") + "format=json"
        d = get(BASE + url)
        pages += 1
        if cats is None:
            cats = d["nestedCategories"]["categories"]
        items += d["items"]
        p = d.get("pagination") or {}
        url = p.get("nextPageUrl") if p.get("nextPage") else None
    return items, cats, pages


def sold_out(it):
    vs = it.get("variants") or []
    return bool(vs) and all((not v.get("unlimited")) and (v.get("qtyInStock") or 0) <= 0 for v in vs)


def price(it):
    """(prix normal, prix soldé ou 0) en cents, sur la variante la moins chère."""
    vs = it.get("variants") or []
    if not vs:
        return 0, 0
    best = min(vs, key=lambda v: (v.get("salePrice") if v.get("onSale") else v.get("price")) or 0)
    sale = best.get("salePrice") if best.get("onSale") else 0
    return best.get("price") or 0, sale or 0


def images(it):
    """(vignette, image au survol) comme sur la grille Squarespace : la vignette est l'image
    choisie pour le produit (assetUrl du produit) sinon la 1re de la galerie ; le survol est
    la 2e image de la galerie. Préfixe CDN retiré pour alléger, remis côté navigateur."""
    gallery = [s.get("assetUrl") or "" for s in it.get("items") or []]
    gallery = [u for u in gallery if u.startswith(IMG_PREFIX)]
    own = it.get("assetUrl") or ""
    cover = own if own.startswith(IMG_PREFIX) else (gallery[0] if gallery else "")
    hover = gallery[1] if len(gallery) > 1 else ""   # Squarespace prend la 2e image de la galerie
    cut = lambda u: u[len(IMG_PREFIX):] if u else ""
    return cut(cover), cut(hover)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="shop-index.json")
    a = ap.parse_args()

    raw, tree, pages = fetch_all()
    artists = next(c for c in tree if c["displayName"] == "Artists")
    artist_cats = {c["id"]: c["displayName"] for c in artists["children"]}
    type_cats = {c["id"]: c["displayName"] for c in tree if c["id"] != artists["id"]}
    slugs = {c["id"]: c.get("shortSlug", "") for c in tree + artists["children"]}

    seen, rows = set(), []
    for it in raw:
        if it["id"] in seen or not it.get("fullUrl", "").startswith("/shop/p/"):
            continue
        seen.add(it["id"])
        p, s = price(it)
        cover, hover = images(it)
        cids = it.get("categoryIds") or []
        rows.append([
            it["urlId"],                                   # 0 lien : /shop/p/<urlId>
            it["title"],                                   # 1 titre "Artiste | ŒUVRE"
            cover,                                         # 2 vignette
            p // 100,                                      # 3 prix USD
            s // 100,                                      # 4 prix soldé USD (0 = pas soldé)
            1 if sold_out(it) else 0,                      # 5 épuisé
            [k for k, c in enumerate(artist_cats) if c in cids],  # 6 index d'artistes
            [k for k, c in enumerate(type_cats) if c in cids],    # 7 index de types
            hover,                                         # 8 image au survol ("" = aucune)
        ])

    out = {
        "v": 1,
        "built": int(time.time()),
        "artists": list(artist_cats.values()),
        "types": list(type_cats.values()),
        "artistSlugs": [slugs[c] for c in artist_cats],   # /shop/artists/<slug>
        "typeSlugs": [slugs[c] for c in type_cats],       # /shop/<slug>
        "artistsSlug": artists.get("shortSlug", "artists"),
        "items": rows,
    }
    if len(rows) < 500:  # garde-fou : ne jamais publier un index tronqué
        sys.exit(f"index anormalement petit ({len(rows)} produits), abandon")
    with open(a.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    raw_size = len(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode())
    gz = len(gzip.compress(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()))
    so = sum(r[5] for r in rows)
    print(f"{len(rows)} produits ({len(rows)-so} dispo, {so} épuisés), {pages} pages lues, "
          f"{raw_size//1024} Ko ({gz//1024} Ko compressé) -> {a.out}")


if __name__ == "__main__":
    main()
