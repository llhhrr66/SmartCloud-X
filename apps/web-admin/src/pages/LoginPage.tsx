import { useState } from "react";
import { adminApi } from "../lib/api";
import type { AdminSession } from "../types";
import { Field, TextInput } from "../components/FormControls";
import { useToast } from "../components/Toast";

export function LoginPage({ onLogin }: { onLogin: (session: AdminSession) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("Admin123!");
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      onLogin(await adminApi.login(username, password));
      toast.push("登录成功", "success");
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "登录失败", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-hero">
        <div className="login-hero-grid" />
        <div className="login-hero-orb" />
        <div className="relative">
          <p className="eyebrow">SmartCloud-X Admin</p>
          <h1 className="font-display italic text-white" style={{ margin: "80px 0 16px", maxWidth: 640, fontSize: "clamp(2.5rem, 7vw, 5rem)", lineHeight: 0.95, letterSpacing: "-0.04em" }}>
            企业云服务<br />控制塔
          </h1>
          <span className="block text-base" style={{ maxWidth: 480, color: "#a9d3ff", lineHeight: 1.75 }}>
            统一管理知识库、检索链路、Agent 编排、营销活动与运行时审计。
          </span>
        </div>
      </section>
      <form className="login-card" onSubmit={submit}>
        <div>
          <p className="eyebrow">Secure Access</p>
          <h2 className="text-2xl font-bold m-0">管理员登录</h2>
        </div>
        <Field label="用户名">
          <TextInput value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
        </Field>
        <Field label="密码">
          <TextInput value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" />
        </Field>
        <button className="btn-primary btn-full" disabled={loading} type="submit">
          {loading ? "验证中…" : "进入管理端"}
        </button>
      </form>
    </main>
  );
}
