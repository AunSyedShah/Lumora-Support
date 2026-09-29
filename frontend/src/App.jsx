import { Navigate, Route, Routes } from 'react-router-dom'

import { FULL_ACCESS_ROLES, homeFor, useAuth } from './auth/context'
import RequireRole from './auth/RequireRole'
import { Loading } from './components/ui'
import CustomerLayout from './layouts/CustomerLayout'
import StaffLayout from './layouts/StaffLayout'
import Assistant from './pages/admin/Assistant'
import Catalog from './pages/admin/Catalog'
import People from './pages/admin/People'
import Policies from './pages/admin/Policies'
import Products from './pages/admin/Products'
import Rules from './pages/admin/Rules'
import SettingsLayout from './pages/admin/SettingsLayout'
import MyComplaints from './pages/customer/MyComplaints'
import MyOrders from './pages/customer/MyOrders'
import NewComplaint from './pages/customer/NewComplaint'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import Register from './pages/Register'
import AgentQueue from './pages/staff/AgentQueue'
import ComplaintList from './pages/staff/ComplaintList'
import ComplaintWorkspace from './pages/staff/ComplaintWorkspace'
import FollowUps from './pages/staff/FollowUps'
import LogComplaint from './pages/staff/LogComplaint'
import Overview from './pages/staff/Overview'
import Reports from './pages/staff/Reports'
import SecondLook from './pages/staff/SecondLook'

function Home() {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  return <Navigate to={user ? homeFor(user.role) : '/login'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route element={<RequireRole roles={['customer']} />}>
        <Route element={<CustomerLayout />}>
          <Route path="/my/complaints" element={<MyComplaints />} />
          <Route path="/my/complaints/new" element={<NewComplaint />} />
          <Route path="/my/complaints/:complaintId" element={<MyComplaints />} />
          <Route path="/my/orders" element={<MyOrders />} />
        </Route>
      </Route>

      <Route element={<RequireRole roles={['agent', 'reviewer', 'manager', 'admin']} />}>
        <Route element={<StaffLayout />}>
          {/* Same split as the navigation rail: typing another role's address leads back home. */}
          <Route element={<RequireRole roles={['agent']} />}>
            <Route path="/work" element={<AgentQueue />} />
            <Route path="/work/follow-ups" element={<FollowUps />} />
            <Route path="/work/complaints/:complaintId" element={<ComplaintWorkspace />} />
          </Route>
          <Route path="/complaints/new" element={<LogComplaint />} />
          <Route path="/complaints/:complaintId" element={<ComplaintWorkspace />} />
          <Route element={<RequireRole roles={FULL_ACCESS_ROLES} />}>
            <Route path="/review" element={<SecondLook />} />
            <Route path="/complaints" element={<ComplaintList />} />
            <Route path="/reports" element={<Reports />} />
          </Route>
          <Route element={<RequireRole roles={['manager', 'admin']} />}>
            <Route path="/overview" element={<Overview />} />
          </Route>
          <Route element={<RequireRole roles={['admin']} />}>
            <Route path="/settings" element={<SettingsLayout />}>
              <Route index element={<Navigate to="/settings/policies" replace />} />
              <Route path="policies" element={<Policies />} />
              <Route path="rules" element={<Rules />} />
              <Route path="catalog" element={<Catalog />} />
              <Route path="products" element={<Products />} />
              <Route path="assistant" element={<Assistant />} />
              <Route path="people" element={<People />} />
            </Route>
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
