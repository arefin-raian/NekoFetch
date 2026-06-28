from types import SimpleNamespace as NS
from nekofetch.ui import log_sections as S
import nekofetch.services.log_channel_service as svc  # import-check
stats = NS(total_users=42, total_downloads=128, queue_size=3, failed_tasks=1, published=57,
           most_requested=[("Attack on Titan",12),("Naruto",9)])
print(S.dashboard_section(stats, stats.most_requested, "12:00:00 UTC")); print("----")
print(S.pending_section([{"code":"REQ-1001","title":"Bleach","by":"998877"}], "12:00:00 UTC")); print("----")
print(S.active_section([{"title":"One Piece","stage":"downloading","progress":63,"eta_seconds":425}], "12:00:00 UTC")); print("----")
print(S.completed_section([{"title":"Hellsing","seasons":"S1"}], "12:00:00 UTC")); print("----")
print(S.notices_section([S.notice_line("request","submitted","12:00:01 UTC","<b>code:</b> REQ-1001"),
                         S.notice_line("error","download_failed","12:00:05 UTC","<b>job:</b> 7")], "12:00:05 UTC")); print("----")
print(S.request_card("REQ-1001","Bleach","998877","Entire Series"))
print("OK service import:", bool(svc.LogChannelService))
