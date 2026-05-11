import { createBrowserRouter, Navigate } from "react-router-dom";
import { lazy, Suspense } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { RequireAuth, RedirectIfAuthed } from "./RequireAuth";
import { Loading } from "@/components/ui/Empty";

const LoginPage = lazy(() => import("@/pages/auth/LoginPage"));
const ForgotPasswordPage = lazy(() => import("@/pages/auth/ForgotPasswordPage"));
const DocumentViewerPage = lazy(() => import("@/pages/DocumentViewerPage").then((module) => ({ default: module.DocumentViewerPage })));

const DashboardPage = lazy(() => import("@/pages/dashboard/DashboardPage"));
const ChatPage = lazy(() => import("@/pages/chat/ChatPage"));
const ChatArchivedPage = lazy(() => import("@/pages/chat/ChatArchivedPage"));
const ChatMessagesPage = lazy(() => import("@/pages/chat/ChatMessagesPage"));

const OrderListPage = lazy(() => import("@/pages/orders/OrderListPage"));
const OrderDetailPage = lazy(() => import("@/pages/orders/OrderDetailPage"));
const RefundListPage = lazy(() => import("@/pages/orders/RefundListPage"));
const RefundRequestPage = lazy(() => import("@/pages/orders/RefundRequestPage"));

const TicketListPage = lazy(() => import("@/pages/tickets/TicketListPage"));
const TicketDetailPage = lazy(() => import("@/pages/tickets/TicketDetailPage"));
const NewTicketPage = lazy(() => import("@/pages/tickets/NewTicketPage"));

const BillingOverviewPage = lazy(() => import("@/pages/billing/BillingOverviewPage"));
const BillingDetailsPage = lazy(() => import("@/pages/billing/BillingDetailsPage"));
const InvoicesPage = lazy(() => import("@/pages/billing/InvoicesPage"));

const IcpListPage = lazy(() => import("@/pages/icp/IcpListPage"));
const IcpDetailPage = lazy(() => import("@/pages/icp/IcpDetailPage"));
const NewIcpPage = lazy(() => import("@/pages/icp/NewIcpPage"));
const IcpPrecheckPage = lazy(() => import("@/pages/icp/IcpPrecheckPage"));

const CampaignsPage = lazy(() => import("@/pages/marketing/CampaignsPage"));
const CopyGenerationPage = lazy(() => import("@/pages/marketing/CopyGenerationPage"));
const PosterTasksPage = lazy(() => import("@/pages/marketing/PosterTasksPage"));
const NewPosterPage = lazy(() => import("@/pages/marketing/NewPosterPage"));
const PosterDetailPage = lazy(() => import("@/pages/marketing/PosterDetailPage"));

const ResearchListPage = lazy(() => import("@/pages/research/ResearchListPage"));
const NewResearchPage = lazy(() => import("@/pages/research/NewResearchPage"));
const ResearchReportPage = lazy(() => import("@/pages/research/ResearchReportPage"));

const ProfilePage = lazy(() => import("@/pages/profile/ProfilePage"));
const SecurityPage = lazy(() => import("@/pages/profile/SecurityPage"));

const wrap = (el: React.ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <RedirectIfAuthed>{wrap(<LoginPage />)}</RedirectIfAuthed>,
  },
  {
    path: "/forgot-password",
    element: <RedirectIfAuthed>{wrap(<ForgotPasswordPage />)}</RedirectIfAuthed>,
  },
  {
    path: "/document-viewer",
    element: wrap(<DocumentViewerPage />),
  },
  {
    path: "/",
    element: <RequireAuth><AppShell /></RequireAuth>,
    children: [
      { index: true, element: wrap(<DashboardPage />) },
      { path: "dashboard", element: <Navigate to="/" replace /> },

      { path: "chat", element: wrap(<ChatPage />) },
      { path: "chat/:conversationId", element: wrap(<ChatPage />) },
      { path: "chat/archived", element: wrap(<ChatArchivedPage />) },
      { path: "chat/messages", element: wrap(<ChatMessagesPage />) },

      { path: "orders", element: wrap(<OrderListPage />) },
      { path: "orders/refunds", element: wrap(<RefundListPage />) },
      { path: "orders/refunds/:refundNo", element: wrap(<RefundListPage />) },
      { path: "orders/:orderNo", element: wrap(<OrderDetailPage />) },
      { path: "orders/:orderNo/refund", element: wrap(<RefundRequestPage />) },

      { path: "tickets", element: wrap(<TicketListPage />) },
      { path: "tickets/new", element: wrap(<NewTicketPage />) },
      { path: "tickets/:ticketNo", element: wrap(<TicketDetailPage />) },

      { path: "billing", element: wrap(<BillingOverviewPage />) },
      { path: "billing/details", element: wrap(<BillingDetailsPage />) },
      { path: "billing/invoices", element: wrap(<InvoicesPage />) },

      { path: "icp", element: wrap(<IcpListPage />) },
      { path: "icp/precheck", element: wrap(<IcpPrecheckPage />) },
      { path: "icp/new", element: wrap(<NewIcpPage />) },
      { path: "icp/:applicationNo", element: wrap(<IcpDetailPage />) },

      { path: "marketing", element: wrap(<CampaignsPage />) },
      { path: "marketing/copy", element: wrap(<CopyGenerationPage />) },
      { path: "marketing/posters", element: wrap(<PosterTasksPage />) },
      { path: "marketing/posters/new", element: wrap(<NewPosterPage />) },
      { path: "marketing/posters/:taskId", element: wrap(<PosterDetailPage />) },

      { path: "research", element: wrap(<ResearchListPage />) },
      { path: "research/new", element: wrap(<NewResearchPage />) },
      { path: "research/:taskId", element: wrap(<ResearchReportPage />) },

      { path: "profile", element: wrap(<ProfilePage />) },
      { path: "profile/security", element: wrap(<SecurityPage />) },

      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
