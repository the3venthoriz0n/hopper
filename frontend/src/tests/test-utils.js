import React from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const AllTheProviders = ({ children, initialEntries = ['/'] }) => {
  return (
    <MemoryRouter 
      initialEntries={initialEntries}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      {children}
    </MemoryRouter>
  );
};

const customRender = (ui, options = {}) => {
  const { initialEntries, ...renderOptions } = options;
  return render(ui, { 
    wrapper: (props) => <AllTheProviders {...props} initialEntries={initialEntries} />, 
    ...renderOptions 
  });
};

export * from '@testing-library/react';
export { customRender as render };
