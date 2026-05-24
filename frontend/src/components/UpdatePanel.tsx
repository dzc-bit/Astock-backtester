import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Download, RefreshCw, ShieldAlert } from "lucide-react";
import {
  createTauriUpdateApi,
  translateUpdateError,
  type AvailableUpdate,
  type InstallEvent,
  type UpdateApi
} from "../updateClient";

type UpdatePanelProps = {
  api?: UpdateApi;
};

type PanelState = "idle" | "checking" | "available" | "current" | "installing" | "error";

function formatProgress(receivedBytes: number, totalBytes?: number): string {
  if (!totalBytes || totalBytes <= 0) {
    return `已下载 ${receivedBytes} 字节`;
  }
  return `下载进度 ${Math.round((receivedBytes / totalBytes) * 100)}%`;
}

export function UpdatePanel({ api: injectedApi }: UpdatePanelProps) {
  const api = useMemo(() => injectedApi ?? createTauriUpdateApi(), [injectedApi]);
  const runtime = api.isRuntime();
  const [version, setVersion] = useState("...");
  const [state, setState] = useState<PanelState>("idle");
  const [message, setMessage] = useState(runtime ? "可检查桌面端更新" : "浏览器预览不可安装更新");
  const [update, setUpdate] = useState<AvailableUpdate | null>(null);
  const [receivedBytes, setReceivedBytes] = useState(0);
  const [totalBytes, setTotalBytes] = useState<number | undefined>();

  useEffect(() => {
    let active = true;

    api.getVersion()
      .then((currentVersion) => {
        if (active) {
          setVersion(currentVersion);
        }
      })
      .catch(() => {
        if (active) {
          setVersion("未知");
        }
      });

    return () => {
      active = false;
    };
  }, [api]);

  const checkForUpdate = async () => {
    setState("checking");
    setMessage("正在检查更新...");
    setUpdate(null);

    try {
      const available = await api.check();
      if (available) {
        setUpdate(available);
        setState("available");
        setMessage(`发现新版本 ${available.version}`);
      } else {
        setState("current");
        setMessage("当前已是最新版本");
      }
    } catch (caught) {
      setState("error");
      setMessage(translateUpdateError(caught));
    }
  };

  const handleInstallEvent = (event: InstallEvent) => {
    if (event.event === "Started") {
      setReceivedBytes(0);
      setTotalBytes(event.data.contentLength);
      setMessage(event.data.contentLength ? "开始下载更新" : "正在下载更新");
      return;
    }
    if (event.event === "Progress") {
      setReceivedBytes((current) => {
        const next = current + event.data.chunkLength;
        const knownTotal = event.data.contentLength ?? totalBytes;
        if (event.data.contentLength) {
          setTotalBytes(event.data.contentLength);
        }
        setMessage(formatProgress(next, knownTotal));
        return next;
      });
      return;
    }
    setMessage("更新安装完成，正在重启...");
  };

  const installAndRelaunch = async () => {
    if (!update) {
      return;
    }
    setState("installing");
    setReceivedBytes(0);
    setTotalBytes(undefined);
    setMessage("准备安装更新...");

    try {
      await update.downloadAndInstall(handleInstallEvent);
      await api.relaunch();
    } catch (caught) {
      setState("error");
      setMessage(translateUpdateError(caught));
    }
  };

  const busy = state === "checking" || state === "installing";
  const statusRole = state === "error" ? "alert" : "status";

  return (
    <section className={`update-panel ${state === "error" ? "has-error" : ""}`} aria-label="应用更新">
      <div className="update-panel-main">
        <span className="status-pill update-version">
          <CheckCircle2 size={16} aria-hidden="true" />
          当前版本 {version}
        </span>
        <div className="update-panel-actions">
          <button type="button" onClick={checkForUpdate} disabled={busy || !runtime}>
            <RefreshCw size={16} aria-hidden="true" />
            检查更新
          </button>
          {update ? (
            <button className="primary-button" type="button" onClick={installAndRelaunch} disabled={busy}>
              <Download size={16} aria-hidden="true" />
              安装并重启
            </button>
          ) : null}
        </div>
      </div>
      <div className="update-status" role={statusRole}>
        {state === "error" ? <ShieldAlert size={16} aria-hidden="true" /> : null}
        <span>{message}</span>
      </div>
      {update ? (
        <div className="update-details">
          <strong>更新说明</strong>
          {update.date ? <span>发布日期 {update.date}</span> : null}
          {update.body ? <p>{update.body}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
