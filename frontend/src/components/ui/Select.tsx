import { Select as AntSelect } from "antd";
import type { SelectProps as AntSelectProps } from "antd";
import { Children, isValidElement, useMemo } from "react";

interface OptionLike {
  value?: string | number;
  children?: React.ReactNode;
}

interface SelectProps extends Omit<AntSelectProps, "children" > {
  children?: React.ReactNode;
}

export function Select({ children, options, ...props }: SelectProps) {
  const derivedOptions = useMemo(() => {
    if (options) return options;
    if (!children) return [];
    return Children.toArray(children)
      .filter(isValidElement<OptionLike>)
      .map((child) => ({
        value: child.props.value,
        label: child.props.children,
      }));
  }, [children, options]);

  return <AntSelect {...props} options={derivedOptions} />;
}
