from .db import one


# Reused by the feed, direct post route and every file route.
def visibility(alias="p"):
    return f"""({alias}.state!='deleted' AND (
      {alias}.owner_id=:viewer OR ({alias}.state='published' AND (
        {alias}.audience='all' OR
        ({alias}.audience='followers' AND EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=:viewer AND f.followed_id={alias}.owner_id)) OR
        ({alias}.audience='selected' AND EXISTS(SELECT 1 FROM post_viewers v WHERE v.post_id={alias}.id AND v.user_id=:viewer)) OR
        ({alias}.audience='groups' AND EXISTS(SELECT 1 FROM post_groups pg JOIN group_members gm ON gm.group_id=pg.group_id WHERE pg.post_id={alias}.id AND gm.user_id=:viewer))
      ))))"""


def can_view(user_id, post_id, media=None):
    user = one("SELECT approved FROM users WHERE id=?", (user_id,))
    if not user or not user["approved"]:
        return False
    post = one(
        f"SELECT p.* FROM posts p WHERE p.id=:post AND {visibility()}",
        {"post": post_id, "viewer": user_id},
    )
    if not post:
        return False
    if media is None:
        return True
    return media["post_id"] == post_id and (
        post["owner_id"] == user_id or bool(media["source_id"] and media["active"])
    )
