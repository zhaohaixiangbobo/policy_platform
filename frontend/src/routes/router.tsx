/**
 * 文件说明：声明M0至M4业务路由和浏览器基线冒烟入口。
 */
import { createBrowserRouter } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { Spin } from 'antd';

import { BasicLayout } from '../layouts/BasicLayout';
import { AboutPage } from '../pages/AboutPage';
import { BrowserBaselinePage } from '../pages/BrowserBaselinePage';
import { ChatPage } from '../pages/ChatPage';
import { DiagnosticsPage } from '../pages/DiagnosticsPage';
import { DiagnosticDetailPage } from '../pages/DiagnosticDetailPage';
import { DocumentDetailPage } from '../pages/DocumentDetailPage';
import { DocumentsPage } from '../pages/DocumentsPage';
import { HomePage } from '../pages/HomePage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { PdfEntryPage } from '../pages/PdfEntryPage';
import { LoginPage } from '../pages/LoginPage';
import { ChangePasswordPage } from '../pages/ChangePasswordPage';
import { RequireAdmin, RequireAuthenticated } from '../auth/AuthContext';
import { ManagementLayout } from '../layouts/ManagementLayout';
import { TaskCenterPage } from '../pages/admin/TaskCenterPage';
import { ReviewWorkbenchPage } from '../pages/admin/ReviewWorkbenchPage';
import { UserAccessPage } from '../pages/admin/UserAccessPage';

const ProcessDesignerPage = lazy(() => import('../pages/admin/ProcessDesignerPage').then((module) => ({ default: module.ProcessDesignerPage })));
const RelationsPage = lazy(() => import('../pages/admin/RelationsPage').then((module) => ({ default: module.RelationsPage })));
const KnowledgeGovernancePage = lazy(() => import('../pages/admin/KnowledgeGovernancePage').then((module) => ({ default: module.KnowledgeGovernancePage })));

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { element: <RequireAuthenticated />, children: [{ path: '/change-password', element: <ChangePasswordPage /> }] },
  {
    element: <RequireAdmin />,
    children: [{
      path: '/admin',
      element: <ManagementLayout />,
      children: [
        { index: true, element: <TaskCenterPage /> },
        { path: 'jobs', element: <TaskCenterPage /> },
        { path: 'reviews', element: <ReviewWorkbenchPage /> },
        { path: 'knowledge', element: <Suspense fallback={<div className="route-loading"><Spin size="large" /></div>}><KnowledgeGovernancePage /></Suspense> },
        { path: 'relations', element: <Suspense fallback={<div className="route-loading"><Spin size="large" /></div>}><RelationsPage /></Suspense> },
        { path: 'processes', element: <Suspense fallback={<div className="route-loading"><Spin size="large" /></div>}><ProcessDesignerPage /></Suspense> },
        { path: 'users', element: <UserAccessPage /> },
      ],
    }],
  },
  {
    element: <RequireAuthenticated />,
    children: [{
      path: '/',
      element: <BasicLayout />,
      children: [
      { index: true, element: <HomePage /> },
      {
        path: 'chat',
        element: <ChatPage />,
      },
      {
        path: 'chat/:sessionId',
        element: <ChatPage />,
      },
      {
        path: 'documents',
        element: <DocumentsPage />,
      },
      {
        path: 'documents/:documentId',
        element: <DocumentDetailPage />,
      },
      {
        path: 'documents/:documentId/pdf',
        element: <PdfEntryPage />,
      },
      { path: 'diagnostics/requests', element: <DiagnosticsPage /> },
      { path: 'diagnostics/requests/:requestId', element: <DiagnosticDetailPage /> },
      { path: 'settings/about', element: <AboutPage /> },
      { path: 'smoke/browser-baseline', element: <BrowserBaselinePage /> },
      { path: '*', element: <NotFoundPage /> },
      ],
    }],
  },
]);
