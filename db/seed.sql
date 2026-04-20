/* 
  [Seed Data]
  1) We must seed PK first, then we can seed FK

  2a) Realistically, only outlets and service_categories_colors need to be seeded
  2b) However, we just seed extra stuff for now (make the website look better lol)
*/


-- Outlets
INSERT INTO outlets (id, name, address, phone, active)
VALUES
  (1, 'Outlet One', '123 Example Street, City 000001', '61234567', true),
  (2, 'Outlet Two', '456 Example Avenue, City 000002', '62345678', true)
ON CONFLICT (id) DO NOTHING;


-- Service Category Colors
INSERT INTO service_categories_colors (id, name, hex)
VALUES
  (1, 'Blue', '#93C5FD'),
  (2, 'Dark Blue', '#7CAEF0'),
  (3, 'Jordy Blue', '#A5B4FC'),
  (4, 'Indigo', '#B8BFF8'),
  (5, 'Lavender', '#D8B4FE'),
  (6, 'Purple', '#E0B0FF'),
  (7, 'Pink', '#FBCFE8'),
  (8, 'Blood Orange', '#FDBA74'),
  (9, 'Orange', '#f3cda2ff'),
  (10, 'Amber', '#ecd67eff'),
  (11, 'Yellow', '#FDE047'),
  (12, 'Lime', '#d2d691ff'),
  (13, 'Green', '#86EFAC'),
  (14, 'Teal', '#60cfbfff'),
  (15, 'Cyan', '#9DCBE6FF')
ON CONFLICT (id) DO NOTHING;


-- Service Categories
INSERT INTO service_categories (id, title, color, description)
VALUES
  (1, 'Facial', 'Cyan', 'Deep-cleansing, hydrating and anti-aging facial treatments'),
  (2, 'Massage', 'Teal', 'Therapeutic massages for relaxation and muscle relief'),
  (3, 'Nails', 'Lime', 'Manicure and pedicure services, classic & gel'),
  (4, 'Hair', 'Amber', 'Haircuts, styling, coloring and treatments'),
  (5, 'Wellness', 'Orange', 'Body wraps, scrubs and holistic wellness services')
ON CONFLICT (id) DO NOTHING;


-- Services 
INSERT INTO services (id, name, category_id, description, duration, price_type, credit_cost, cash_price, active, online_bookings, comissions)
VALUES
  (1, 'Facial Treatment', 1, 'Deep cleansing facial', 90, 'Fixed', 2, 190, true, true, true),
  (2, 'Deep Tissue Massage', 2, 'Therapeutic massage', 60, 'Fixed', 2, 180, true, true, true),
  (3, 'Manicure', 3, 'Classic manicure', 45, 'Fixed', 1, 80, true, true, true),
  (4, 'Pedicure', 3, 'Relaxing pedicure', 60, 'Fixed', 1, 90, false, true, true),
  (5, 'Gel Manicure', 3, 'Long-lasting gel manicure', 75, 'Fixed', 1, 120, false, true, true),
  (6, 'Aromatherapy Massage', 2, 'Relaxing massage with essential oils', 60, 'Fixed', 3, 200, true, true, true),
  (7, 'Haircut & Style', 4, 'Precision cut and styling session', 45, 'Fixed', 1, 60, true, true, true),
  (8, 'Detox Body Wrap', 5, 'Full-body seaweed detox wrap to purify, hydrate, and rejuvenate skin', 75, 'Fixed', 3, 220, true, true, true)
ON CONFLICT (id) DO NOTHING;


-- Service-Outlet link table 
INSERT INTO service_outlet (service_id, outlet_id)
VALUES
  (1, 1),
  (2, 1),
  (3, 1),
  (4, 1),
  (5, 2),
  (6, 2),
  (7, 2),
  (8, 2)
ON CONFLICT (service_id, outlet_id) DO NOTHING;


-- Staffs
INSERT INTO staffs (id, first_name, last_name, email, phone, role, bookable,active)
VALUES
  (1, 'Sarah', 'Adams', 'sarah@example.com', '91234567', 'Senior Therapist', true, true),
  (2, 'Maria', 'Johnson', 'maria@example.com', '92345678', 'Nail Specialist', true, true),
  (3, 'Jennifer', 'Kim', 'jennifer@example.com', '93456789', 'Massage Therapist', false, true),
  (4, 'Natalie', 'Leong', 'natalie@example.com', '96789012', 'Facial Specialist', false, false),
  (5, 'Lisa', 'Wong', 'lisa@example.com', '94567890', 'Senior Therapist', true, false),
  (6, 'Rachel', 'Tan', 'rachel@example.com', '95678901', 'Facial Specialist', true, false),
  (7, 'Shireen', 'Ling', 'shireen@example.com', '97890123', 'Beauty Therapist', false, true),
  (8, 'Chloe', 'Mok', 'chloe@example.com', '98901234', 'Aesthetician', true, false)
ON CONFLICT (id) DO NOTHING;


-- Staff-Outlet link table 
INSERT INTO staff_outlet (staff_id, outlet_id)
VALUES
  (1, 1),
  (1, 2),  -- Sarah appears in both outlets 
  (2, 1),
  (3, 1),
  (4, 1),
  (5, 1),
  (6, 2),
  (7, 2),
  (8, 2)
ON CONFLICT (staff_id, outlet_id) DO NOTHING;


-- Customers
INSERT INTO customers (id, first_name, last_name, email, phone, birthday, membership_type, membership_status, preferred_therapist_id, preferred_outlet_id, allergies, reminders, credit_balance, created_at)
VALUES
  (1, 'Emily', 'Chen', 'emily.chen@email.com', '91112222', NULL, NULL, 'Active', 1, 1, ARRAY['Essential oils', 'Parabens', 'Latex'], 'Email + SMS', 2, NOW()),
  (2, 'Jessica', 'Lim', 'jessica.lim@email.com', '93334444', NULL, NULL, 'Active', 2, 1, ARRAY['Essential oils', 'Parabens', 'Latex'], 'Email + SMS', 2, NOW()),
  (3, 'Amanda', 'Ng', 'amanda.ng@email.com', '95556666', NULL, NULL, 'Active', 5, 2, ARRAY['Essential oils', 'Parabens', 'Latex'], 'Email + SMS', 2, NOW()),
  (4, 'Michelle', 'Tan', 'michelle.tan@email.com', '97778888', NULL, NULL, 'Active', 6, 2, ARRAY['Essential oils', 'Parabens', 'Latex'], 'Email + SMS', 2, NOW())
ON CONFLICT (id) DO NOTHING;


/* 
  [Id sequence sync]
  1) Supabase maintains an id sequence for each table (ensure unique pk)
  2) We want to explicitly tell supabase to push the sequence up to max(id)

  3a) So future inserts work
  3b) So we can explicitly reference id in this script

  4) Link tables are excluded since they do not use supabase's id field
*/


SELECT setval(pg_get_serial_sequence('outlets', 'id'), (SELECT MAX(id) FROM outlets));
SELECT setval(pg_get_serial_sequence('service_categories_colors', 'id'), (SELECT MAX(id) FROM service_categories_colors));
SELECT setval(pg_get_serial_sequence('service_categories', 'id'), (SELECT MAX(id) FROM service_categories));
SELECT setval(pg_get_serial_sequence('services', 'id'), (SELECT MAX(id) FROM services));
SELECT setval(pg_get_serial_sequence('staffs', 'id'), (SELECT MAX(id) FROM staffs));
SELECT setval(pg_get_serial_sequence('customers', 'id'), (SELECT MAX(id) FROM customers));