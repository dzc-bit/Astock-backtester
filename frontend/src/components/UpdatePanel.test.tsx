import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UpdatePanel } from "./UpdatePanel";
import type { InstallEvent, UpdateApi } from "../updateClient";

function createApi(overrides: Partial<UpdateApi> = {}): UpdateApi {
  return {
    isRuntime: () => true,
    getVersion: vi.fn().mockResolvedValue("0.1.0"),
    check: vi.fn().mockResolvedValue(null),
    relaunch: vi.fn().mockResolvedValue(undefined),
    ...overrides
  };
}

describe("UpdatePanel", () => {
  it("shows the current version and reports no update", async () => {
    const api = createApi();
    const user = userEvent.setup();

    render(<UpdatePanel api={api} />);

    expect(await screen.findByText("当前版本 0.1.0")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "检查更新" }));

    expect(await screen.findByRole("status")).toHaveTextContent("当前已是最新版本");
  });

  it("installs an available update, shows notes, progress, and relaunches", async () => {
    const user = userEvent.setup();
    const downloadAndInstall = vi.fn(async (onEvent?: (event: InstallEvent) => void) => {
      onEvent?.({ event: "Started", data: { contentLength: 200 } });
      onEvent?.({ event: "Progress", data: { chunkLength: 100 } });
    });
    const relaunch = vi.fn().mockResolvedValue(undefined);
    const api = createApi({
      check: vi.fn().mockResolvedValue({
        version: "0.2.0",
        date: "2026-05-24",
        body: "修复回测结果导出问题",
        downloadAndInstall
      }),
      relaunch
    });

    render(<UpdatePanel api={api} />);

    await user.click(await screen.findByRole("button", { name: "检查更新" }));

    expect(await screen.findByText("发现新版本 0.2.0")).toBeInTheDocument();
    expect(screen.getByText("修复回测结果导出问题")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "安装并重启" }));

    expect(downloadAndInstall).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("status")).toHaveTextContent("下载进度 50%");
    await waitFor(() => expect(relaunch).toHaveBeenCalledTimes(1));
  });

  it("translates signature failures without leaking raw plugin details", async () => {
    const user = userEvent.setup();
    const api = createApi({
      check: vi.fn().mockRejectedValue(new Error("signature mismatch"))
    });

    render(<UpdatePanel api={api} />);

    await user.click(await screen.findByRole("button", { name: "检查更新" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("更新文件校验失败");
    expect(alert).not.toHaveTextContent("signature mismatch");
  });

  it("disables checking in browser preview", async () => {
    const api = createApi({ isRuntime: () => false });

    render(<UpdatePanel api={api} />);

    expect(await screen.findByText("当前版本 0.1.0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "检查更新" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("浏览器预览不可安装更新");
  });
});
